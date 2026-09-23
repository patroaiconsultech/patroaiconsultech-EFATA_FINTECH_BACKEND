from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url


pytestmark = pytest.mark.postgres

ROOT = Path(__file__).resolve().parents[1]
OLD_LENGTH = 36
NEW_LENGTH = 255
TARGET_REVISION = "0010_audit_resource_id_r11"
PREVIOUS_REVISION = "0009_sync_job_study_link_r11"


def _postgres_source_url():
    raw = os.getenv("FINTECH_DATABASE_URL", "")
    if os.getenv("RUN_POSTGRES_MIGRATION_TESTS") != "1":
        pytest.skip(
            "requires RUN_POSTGRES_MIGRATION_TESTS=1",
            allow_module_level=True,
        )
    if not raw.startswith("postgresql"):
        pytest.skip(
            "requires a real PostgreSQL FINTECH_DATABASE_URL",
            allow_module_level=True,
        )
    return make_url(raw)


SOURCE_URL = _postgres_source_url()


@pytest.fixture()
def migration_database_url():
    # Dedicated DB per test: migration tests must not mutate the functional
    # fintech_ci database used by the backend/concurrency suite.
    suffix = uuid4().hex[:12]
    db_name = f"fintech_pgfix006_migration_ci_{suffix}"

    admin_url = SOURCE_URL.set(database="postgres")
    admin_engine = create_engine(
        admin_url,
        isolation_level="AUTOCOMMIT",
        future=True,
    )
    quoted = admin_engine.dialect.identifier_preparer.quote(db_name)

    with admin_engine.connect() as connection:
        connection.exec_driver_sql(f"CREATE DATABASE {quoted}")

    test_url = SOURCE_URL.set(database=db_name)

    try:
        yield test_url.render_as_string(hide_password=False)
    finally:
        # Dispose any SQLAlchemy engine created by this process before
        # dropping. Alembic subprocesses have already terminated.
        with admin_engine.connect() as connection:
            connection.exec_driver_sql(
                f"DROP DATABASE IF EXISTS {quoted} WITH (FORCE)"
            )
        admin_engine.dispose()


def _run_alembic(database_url: str, *args: str, expect_success: bool = True):
    env = os.environ.copy()
    env["FINTECH_DATABASE_URL"] = database_url

    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
    )

    if expect_success and result.returncode != 0:
        raise AssertionError(
            f"Alembic command failed: {args}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )

    return result


def _column_length(database_url: str) -> int:
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            column = next(
                item
                for item in inspect(connection).get_columns(
                    "platform_audit_events"
                )
                if item["name"] == "resource_id"
            )
            return int(column["type"].length)
    finally:
        engine.dispose()


def _revision(database_url: str) -> str:
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            return str(
                connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one()
            )
    finally:
        engine.dispose()


def _force_legacy_36(database_url: str) -> None:
    # 0001 currently uses Base.metadata.create_all(), so when the proposed
    # model is 255 a fresh DB may already be born at 255. This explicit
    # precondition reconstructs the known legacy 0009 schema.
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE platform_audit_events "
                    "ALTER COLUMN resource_id TYPE VARCHAR(36)"
                )
            )
    finally:
        engine.dispose()

    assert _revision(database_url) == PREVIOUS_REVISION
    assert _column_length(database_url) == OLD_LENGTH


def _prepare_legacy_0009(database_url: str) -> None:
    _run_alembic(database_url, "upgrade", PREVIOUS_REVISION)
    _force_legacy_36(database_url)


def _insert_audit_event(database_url: str, resource_id: str) -> str:
    event_id = str(uuid4())
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO platform_audit_events (
                        audit_event_id,
                        tenant_id,
                        actor_id,
                        action,
                        resource_type,
                        resource_id,
                        request_id,
                        correlation_id,
                        detail,
                        occurred_at
                    )
                    VALUES (
                        :audit_event_id,
                        :tenant_id,
                        :actor_id,
                        :action,
                        :resource_type,
                        :resource_id,
                        :request_id,
                        :correlation_id,
                        CAST(:detail AS JSON),
                        CURRENT_TIMESTAMP
                    )
                    """
                ),
                {
                    "audit_event_id": event_id,
                    "tenant_id": "00000000-0000-0000-0000-000000000003",
                    "actor_id": "20000000-0000-0000-0000-000000000003",
                    "action": "PG_FIX_006_MIGRATION_PROOF",
                    "resource_type": "RECONCILIATION",
                    "resource_id": resource_id,
                    "request_id": "90000000-0000-0000-0000-000000000001",
                    "correlation_id": "90000000-0000-0000-0000-000000000001",
                    "detail": '{}',
                },
            )
    finally:
        engine.dispose()
    return event_id


def _resource_id(database_url: str, event_id: str) -> str:
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            return str(
                connection.execute(
                    text(
                        "SELECT resource_id "
                        "FROM platform_audit_events "
                        "WHERE audit_event_id=:event_id"
                    ),
                    {"event_id": event_id},
                ).scalar_one()
            )
    finally:
        engine.dispose()


def test_legacy_36_upgrades_to_255_and_preserves_existing_data(
    migration_database_url,
):
    _prepare_legacy_0009(migration_database_url)
    resource_id = str(uuid4())
    event_id = _insert_audit_event(migration_database_url, resource_id)

    _run_alembic(migration_database_url, "upgrade", TARGET_REVISION)

    assert _revision(migration_database_url) == TARGET_REVISION
    assert _column_length(migration_database_url) == NEW_LENGTH
    assert _resource_id(migration_database_url, event_id) == resource_id


def test_downgrade_to_36_succeeds_when_all_values_fit(
    migration_database_url,
):
    _prepare_legacy_0009(migration_database_url)
    _run_alembic(migration_database_url, "upgrade", TARGET_REVISION)

    resource_id = str(uuid4())
    event_id = _insert_audit_event(migration_database_url, resource_id)

    _run_alembic(migration_database_url, "downgrade", PREVIOUS_REVISION)

    assert _revision(migration_database_url) == PREVIOUS_REVISION
    assert _column_length(migration_database_url) == OLD_LENGTH
    assert _resource_id(migration_database_url, event_id) == resource_id


def test_downgrade_is_blocked_without_truncation_when_value_exceeds_36(
    migration_database_url,
):
    _prepare_legacy_0009(migration_database_url)
    _run_alembic(migration_database_url, "upgrade", TARGET_REVISION)

    resource_id = f"reconciliation-{uuid4()}"
    assert len(resource_id) == 51
    event_id = _insert_audit_event(migration_database_url, resource_id)

    result = _run_alembic(
        migration_database_url,
        "downgrade",
        PREVIOUS_REVISION,
        expect_success=False,
    )

    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "AUDIT_RESOURCE_ID_DOWNGRADE_BLOCKED" in combined

    # Fail-closed means schema and data stay unchanged.
    assert _revision(migration_database_url) == TARGET_REVISION
    assert _column_length(migration_database_url) == NEW_LENGTH
    assert _resource_id(migration_database_url, event_id) == resource_id


@pytest.mark.parametrize("unexpected_length", [64, 128, 512])
def test_upgrade_fails_closed_on_schema_drift(
    migration_database_url,
    unexpected_length,
):
    _prepare_legacy_0009(migration_database_url)

    engine = create_engine(migration_database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE platform_audit_events "
                    f"ALTER COLUMN resource_id "
                    f"TYPE VARCHAR({unexpected_length})"
                )
            )
    finally:
        engine.dispose()

    result = _run_alembic(
        migration_database_url,
        "upgrade",
        TARGET_REVISION,
        expect_success=False,
    )

    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "AUDIT_RESOURCE_ID_SCHEMA_DRIFT" in combined
    assert _revision(migration_database_url) == PREVIOUS_REVISION
    assert _column_length(migration_database_url) == unexpected_length
