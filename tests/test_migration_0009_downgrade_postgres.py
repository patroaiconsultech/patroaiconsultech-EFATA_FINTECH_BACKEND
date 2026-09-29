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
REVISION_0008 = "0008_erp_connector_runtime_r11"
REVISION_0009 = "0009_sync_job_study_link_r11"
HEAD_REVISION = "0010_audit_resource_id_r11"


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
    suffix = uuid4().hex[:12]
    db_name = f"fintech_mig0009_ci_{suffix}"

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
        with admin_engine.connect() as connection:
            connection.exec_driver_sql(
                f"DROP DATABASE IF EXISTS {quoted} WITH (FORCE)"
            )
        admin_engine.dispose()


def _run_alembic(database_url: str, *args: str):
    env = os.environ.copy()
    env["FINTECH_DATABASE_URL"] = database_url

    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=180,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"Alembic command failed: {args}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return result


def _column_names(database_url: str) -> set[str]:
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            return {
                column["name"]
                for column in inspect(connection).get_columns(
                    "integration_sync_jobs"
                )
            }
    finally:
        engine.dispose()


def _foreign_keys(database_url: str) -> list[dict]:
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            return inspect(connection).get_foreign_keys(
                "integration_sync_jobs"
            )
    finally:
        engine.dispose()


def _index_names(database_url: str) -> set[str]:
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            return {
                index["name"]
                for index in inspect(connection).get_indexes(
                    "integration_sync_jobs"
                )
                if index.get("name")
            }
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


def _study_fk_names(database_url: str) -> set[str]:
    return {
        foreign_key["name"]
        for foreign_key in _foreign_keys(database_url)
        if foreign_key.get("name")
        and foreign_key.get("constrained_columns") == ["study_id"]
    }


def _force_legacy_0008_without_study_id(database_url: str) -> None:
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            indexes = {
                index["name"]
                for index in inspect(connection).get_indexes(
                    "integration_sync_jobs"
                )
                if index.get("name")
            }
            if "ix_sync_job_study_created" in indexes:
                connection.execute(
                    text(
                        "DROP INDEX "
                        "IF EXISTS ix_sync_job_study_created"
                    )
                )
            columns = {
                column["name"]
                for column in inspect(connection).get_columns(
                    "integration_sync_jobs"
                )
            }
            if "study_id" in columns:
                connection.execute(
                    text(
                        "ALTER TABLE integration_sync_jobs "
                        "DROP COLUMN study_id"
                    )
                )
    finally:
        engine.dispose()

    assert _revision(database_url) == REVISION_0008
    assert "study_id" not in _column_names(database_url)


def test_downgrade_0009_handles_bootstrap_fk_name(
    migration_database_url,
):
    # Reproduces the CI path: 0001 uses current Base.metadata.create_all(),
    # so study_id and its PostgreSQL-generated FK already exist before 0009.
    _run_alembic(migration_database_url, "upgrade", REVISION_0009)

    assert _revision(migration_database_url) == REVISION_0009
    assert "study_id" in _column_names(migration_database_url)

    study_fk_names = _study_fk_names(migration_database_url)
    assert study_fk_names
    assert "fk_sync_job_study" not in study_fk_names

    _run_alembic(migration_database_url, "downgrade", REVISION_0008)

    assert _revision(migration_database_url) == REVISION_0008
    assert "study_id" not in _column_names(migration_database_url)
    assert "ix_sync_job_study_created" not in _index_names(
        migration_database_url
    )


def test_downgrade_0009_handles_fk_created_by_revision_itself(
    migration_database_url,
):
    _run_alembic(migration_database_url, "upgrade", REVISION_0008)
    _force_legacy_0008_without_study_id(migration_database_url)

    _run_alembic(migration_database_url, "upgrade", REVISION_0009)

    assert _revision(migration_database_url) == REVISION_0009
    assert "study_id" in _column_names(migration_database_url)
    assert "fk_sync_job_study" in _study_fk_names(
        migration_database_url
    )

    _run_alembic(migration_database_url, "downgrade", REVISION_0008)

    assert _revision(migration_database_url) == REVISION_0008
    assert "study_id" not in _column_names(migration_database_url)


def test_clean_head_can_downgrade_to_base_and_reupgrade(
    migration_database_url,
):
    # End-to-end migration-chain proof. No >36 audit resource_id is inserted,
    # so revision 0010 is expected to be safely reversible in this scenario.
    _run_alembic(migration_database_url, "upgrade", "head")
    assert _revision(migration_database_url) == HEAD_REVISION

    _run_alembic(migration_database_url, "downgrade", "base")

    engine = create_engine(migration_database_url, future=True)
    try:
        with engine.connect() as connection:
            assert not inspect(connection).has_table(
                "integration_sync_jobs"
            )
    finally:
        engine.dispose()

    _run_alembic(migration_database_url, "upgrade", "head")
    assert _revision(migration_database_url) == HEAD_REVISION
