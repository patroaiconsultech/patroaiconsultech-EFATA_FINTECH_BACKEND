from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import create_engine, inspect

from app.migration_support import (
    ALEMBIC_VERSION_NUM_LENGTH,
    ALEMBIC_VERSION_TABLE,
    ensure_alembic_version_capacity,
)


def test_repository_revision_ids_fit_configured_version_capacity():
    versions_dir = Path(__file__).resolve().parents[1] / "migrations" / "versions"
    revisions: list[str] = []

    for path in versions_dir.glob("*.py"):
        match = re.search(
            r'^revision\s*=\s*["\']([^"\']+)["\']',
            path.read_text(encoding="utf-8"),
            flags=re.MULTILINE,
        )
        if match:
            revisions.append(match.group(1))

    assert revisions
    assert max(map(len, revisions)) <= ALEMBIC_VERSION_NUM_LENGTH

    # Preserve evidence for the regression that PostgreSQL exposed:
    # at least one historical revision is wider than Alembic's default 32.
    assert any(len(revision) > 32 for revision in revisions)


def test_fresh_version_table_is_created_with_wider_capacity():
    engine = create_engine("sqlite://", future=True)
    try:
        with engine.connect() as connection:
            with connection.begin():
                ensure_alembic_version_capacity(connection)

            columns = inspect(connection).get_columns(ALEMBIC_VERSION_TABLE)
            version_column = next(
                column for column in columns if column["name"] == "version_num"
            )
            assert getattr(version_column["type"], "length", None) == (
                ALEMBIC_VERSION_NUM_LENGTH
            )
    finally:
        engine.dispose()


def test_version_table_capacity_guard_is_idempotent():
    engine = create_engine("sqlite://", future=True)
    try:
        with engine.connect() as connection:
            with connection.begin():
                ensure_alembic_version_capacity(connection)
            with connection.begin():
                ensure_alembic_version_capacity(connection)

            assert inspect(connection).has_table(ALEMBIC_VERSION_TABLE)
    finally:
        engine.dispose()
