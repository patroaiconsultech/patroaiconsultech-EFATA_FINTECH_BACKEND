from __future__ import annotations

from sqlalchemy import (
    Column,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    inspect,
    text,
)
from sqlalchemy.engine import Connection


ALEMBIC_VERSION_TABLE = "alembic_version"
ALEMBIC_VERSION_NUM_LENGTH = 128


def ensure_alembic_version_capacity(connection: Connection) -> None:
    """Ensure Alembic's revision column can hold this repository's revision IDs.

    Alembic's default version table uses VARCHAR(32). This repository has
    historical revision identifiers longer than 32 characters.

    Fresh databases receive VARCHAR(128). Existing PostgreSQL databases with a
    narrower VARCHAR are widened in place before Alembic advances the revision.

    The operation is intentionally limited to the Alembic metadata table; it
    does not mutate application/domain tables.
    """
    inspector = inspect(connection)

    if not inspector.has_table(ALEMBIC_VERSION_TABLE):
        version_table = Table(
            ALEMBIC_VERSION_TABLE,
            MetaData(),
            Column(
                "version_num",
                String(ALEMBIC_VERSION_NUM_LENGTH),
                nullable=False,
            ),
            PrimaryKeyConstraint(
                "version_num",
                name=f"{ALEMBIC_VERSION_TABLE}_pkc",
            ),
        )
        version_table.create(connection)
        return

    version_column = next(
        (
            column
            for column in inspector.get_columns(ALEMBIC_VERSION_TABLE)
            if column["name"] == "version_num"
        ),
        None,
    )
    if version_column is None:
        raise RuntimeError("ALEMBIC_VERSION_COLUMN_MISSING")

    current_length = getattr(version_column["type"], "length", None)
    if current_length is None or current_length >= ALEMBIC_VERSION_NUM_LENGTH:
        return

    dialect = connection.dialect.name

    if dialect == "postgresql":
        connection.execute(
            text(
                "ALTER TABLE alembic_version "
                f"ALTER COLUMN version_num TYPE VARCHAR({ALEMBIC_VERSION_NUM_LENGTH})"
            )
        )
        return

    if dialect == "sqlite":
        # SQLite does not enforce VARCHAR(n) length. Existing local databases
        # therefore remain usable; fresh databases are created at length 128.
        return

    raise RuntimeError(
        "ALEMBIC_VERSION_COLUMN_TOO_NARROW "
        f"dialect={dialect} current={current_length} "
        f"required={ALEMBIC_VERSION_NUM_LENGTH}"
    )
