"""Widen generic platform audit resource IDs.

Revision ID: 0010_audit_resource_id_r11
Revises: 0009_sync_job_study_link_r11
"""

import sqlalchemy as sa
from alembic import op

revision = "0010_audit_resource_id_r11"
down_revision = "0009_sync_job_study_link_r11"
branch_labels = None
depends_on = None

TABLE_NAME = "platform_audit_events"
COLUMN_NAME = "resource_id"
OLD_LENGTH = 36
NEW_LENGTH = 255


def _require_resource_id_column(bind):
    inspector = sa.inspect(bind)

    if not inspector.has_table(TABLE_NAME):
        raise RuntimeError(
            "AUDIT_RESOURCE_ID_SCHEMA_DRIFT "
            f"table={TABLE_NAME} missing=true"
        )

    column = next(
        (
            item
            for item in inspector.get_columns(TABLE_NAME)
            if item["name"] == COLUMN_NAME
        ),
        None,
    )
    if column is None:
        raise RuntimeError(
            "AUDIT_RESOURCE_ID_SCHEMA_DRIFT "
            f"table={TABLE_NAME} column={COLUMN_NAME} missing=true"
        )

    current_length = getattr(column["type"], "length", None)
    if current_length is None:
        raise RuntimeError(
            "AUDIT_RESOURCE_ID_SCHEMA_DRIFT "
            f"table={TABLE_NAME} column={COLUMN_NAME} "
            f"type={column['type']} expected_lengths=[{OLD_LENGTH},{NEW_LENGTH}]"
        )

    return column, int(current_length)


def _alter_resource_id(bind, *, from_length: int, to_length: int) -> None:
    from_type = sa.String(length=from_length)
    to_type = sa.String(length=to_length)

    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(TABLE_NAME, recreate="always") as batch_op:
            batch_op.alter_column(
                COLUMN_NAME,
                existing_type=from_type,
                type_=to_type,
                existing_nullable=False,
            )
        return

    op.alter_column(
        TABLE_NAME,
        COLUMN_NAME,
        existing_type=from_type,
        type_=to_type,
        existing_nullable=False,
    )


def upgrade() -> None:
    bind = op.get_bind()
    _, current_length = _require_resource_id_column(bind)

    if current_length == NEW_LENGTH:
        return

    if current_length != OLD_LENGTH:
        raise RuntimeError(
            "AUDIT_RESOURCE_ID_SCHEMA_DRIFT "
            f"current_length={current_length} "
            f"expected_lengths=[{OLD_LENGTH},{NEW_LENGTH}]"
        )

    _alter_resource_id(
        bind,
        from_length=OLD_LENGTH,
        to_length=NEW_LENGTH,
    )


def downgrade() -> None:
    bind = op.get_bind()
    _, current_length = _require_resource_id_column(bind)

    if current_length == OLD_LENGTH:
        return

    if current_length != NEW_LENGTH:
        raise RuntimeError(
            "AUDIT_RESOURCE_ID_SCHEMA_DRIFT "
            f"current_length={current_length} "
            f"expected_lengths=[{OLD_LENGTH},{NEW_LENGTH}]"
        )

    max_length = bind.execute(
        sa.text(
            "SELECT COALESCE(MAX(LENGTH(resource_id)), 0) "
            "FROM platform_audit_events"
        )
    ).scalar_one()

    if int(max_length or 0) > OLD_LENGTH:
        raise RuntimeError(
            "AUDIT_RESOURCE_ID_DOWNGRADE_BLOCKED "
            f"max_existing_length={max_length} "
            f"target_length={OLD_LENGTH} "
            "manual_data_decision_required=true"
        )

    _alter_resource_id(
        bind,
        from_length=NEW_LENGTH,
        to_length=OLD_LENGTH,
    )
