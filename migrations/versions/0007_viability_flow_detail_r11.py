"""Persist complete FCD monthly flow details.

Revision ID: 0007_viability_flow_detail_r11
Revises: 0006_viability_erp_r11
"""

import sqlalchemy as sa
from alembic import op

revision = "0007_viability_flow_detail_r11"
down_revision = "0006_viability_erp_r11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("viability_monthly_flows")}
    additions = (
        ("project_cash_flow", sa.Numeric(19, 4), "0"),
        ("debt_balance", sa.Numeric(19, 4), "0"),
        ("unlevered_present_value", sa.Numeric(19, 4), "0"),
    )
    for name, column_type, default in additions:
        if name not in columns:
            op.add_column(
                "viability_monthly_flows",
                sa.Column(name, column_type, nullable=False, server_default=sa.text(default)),
            )
            if bind.dialect.name != "sqlite":
                op.alter_column("viability_monthly_flows", name, server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("viability_monthly_flows"):
        return
    columns = {column["name"] for column in inspector.get_columns("viability_monthly_flows")}
    for name in ("unlevered_present_value", "debt_balance", "project_cash_flow"):
        if name in columns:
            op.drop_column("viability_monthly_flows", name)
