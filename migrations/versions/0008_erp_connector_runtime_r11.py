"""Add runtime configuration and result metadata for ERP connectors.

Revision ID: 0008_erp_connector_runtime_r11
Revises: 0007_viability_flow_detail_r11
"""

import sqlalchemy as sa
from alembic import op

revision = "0008_erp_connector_runtime_r11"
down_revision = "0007_viability_flow_detail_r11"
branch_labels = None
depends_on = None


def _columns(bind, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("integration_erp_connections"):
        columns = _columns(bind, "integration_erp_connections")
        if "base_url" not in columns:
            op.add_column(
                "integration_erp_connections",
                sa.Column(
                    "base_url",
                    sa.String(length=512),
                    nullable=False,
                    server_default="https://not-configured.invalid",
                ),
            )
            if bind.dialect.name != "sqlite":
                op.alter_column("integration_erp_connections", "base_url", server_default=None)
        if "resource_map_json" not in columns:
            op.add_column(
                "integration_erp_connections",
                sa.Column("resource_map_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            )
            if bind.dialect.name != "sqlite":
                op.alter_column("integration_erp_connections", "resource_map_json", server_default=None)

    if inspector.has_table("integration_sync_jobs"):
        columns = _columns(bind, "integration_sync_jobs")
        if "result_json" not in columns:
            op.add_column(
                "integration_sync_jobs",
                sa.Column("result_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            )
            if bind.dialect.name != "sqlite":
                op.alter_column("integration_sync_jobs", "result_json", server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("integration_sync_jobs") and "result_json" in _columns(bind, "integration_sync_jobs"):
        op.drop_column("integration_sync_jobs", "result_json")
    if inspector.has_table("integration_erp_connections"):
        columns = _columns(bind, "integration_erp_connections")
        if "resource_map_json" in columns:
            op.drop_column("integration_erp_connections", "resource_map_json")
        if "base_url" in columns:
            op.drop_column("integration_erp_connections", "base_url")
