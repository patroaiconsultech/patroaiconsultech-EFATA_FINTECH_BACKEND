"""Persist viability M1 and read-only ERP integration metadata.

Revision ID: 0006_viability_erp_r11
Revises: 0005_consent_ledger_observability_r10
"""

import sqlalchemy as sa
from alembic import op

revision = "0006_viability_erp_r11"
down_revision = "0005_consent_ledger_observability_r10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("viability_studies"):
        op.create_table(
            "viability_studies",
            sa.Column("study_id", sa.String(length=36), nullable=False),
            sa.Column("tenant_id", sa.String(length=36), nullable=False),
            sa.Column("opportunity_id", sa.String(length=36), nullable=True),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("project_name", sa.String(length=255), nullable=False),
            sa.Column("status", sa.String(length=48), nullable=False),
            sa.Column("base_date", sa.DateTime(timezone=True), nullable=False),
            sa.Column("currency", sa.String(length=3), nullable=False),
            sa.Column("inputs_json", sa.JSON(), nullable=False),
            sa.Column("created_by", sa.String(length=36), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["iam_tenants.tenant_id"]),
            sa.ForeignKeyConstraint(["opportunity_id"], ["marketplace_credit_requests.credit_request_id"]),
            sa.ForeignKeyConstraint(["created_by"], ["iam_users.user_id"]),
            sa.PrimaryKeyConstraint("study_id"),
        )
        op.create_index("ix_viability_study_tenant_status", "viability_studies", ["tenant_id", "status"])
        op.create_index("ix_viability_study_opportunity", "viability_studies", ["opportunity_id"])

    if not inspector.has_table("viability_scenarios"):
        op.create_table(
            "viability_scenarios",
            sa.Column("scenario_id", sa.String(length=36), nullable=False),
            sa.Column("study_id", sa.String(length=36), nullable=False),
            sa.Column("scenario_key", sa.String(length=48), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("overrides_json", sa.JSON(), nullable=False),
            sa.Column("outputs_json", sa.JSON(), nullable=False),
            sa.Column("engine_version", sa.String(length=64), nullable=False),
            sa.Column("created_by", sa.String(length=36), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["study_id"], ["viability_studies.study_id"]),
            sa.ForeignKeyConstraint(["created_by"], ["iam_users.user_id"]),
            sa.PrimaryKeyConstraint("scenario_id"),
            sa.UniqueConstraint("study_id", "scenario_key", name="uq_viability_scenario_key"),
        )
        op.create_index("ix_viability_scenario_study_status", "viability_scenarios", ["study_id", "status"])

    if not inspector.has_table("viability_monthly_flows"):
        op.create_table(
            "viability_monthly_flows",
            sa.Column("flow_id", sa.String(length=36), nullable=False),
            sa.Column("scenario_id", sa.String(length=36), nullable=False),
            sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revenue", sa.Numeric(19, 4), nullable=False),
            sa.Column("equity_contribution", sa.Numeric(19, 4), nullable=False),
            sa.Column("funding_draw", sa.Numeric(19, 4), nullable=False),
            sa.Column("land_cost", sa.Numeric(19, 4), nullable=False),
            sa.Column("construction_cost", sa.Numeric(19, 4), nullable=False),
            sa.Column("other_costs", sa.Numeric(19, 4), nullable=False),
            sa.Column("interest", sa.Numeric(19, 4), nullable=False),
            sa.Column("principal", sa.Numeric(19, 4), nullable=False),
            sa.Column("net_cash_flow", sa.Numeric(19, 4), nullable=False),
            sa.Column("cumulative_cash_flow", sa.Numeric(19, 4), nullable=False),
            sa.Column("discount_factor", sa.Numeric(19, 10), nullable=False),
            sa.Column("present_value", sa.Numeric(19, 4), nullable=False),
            sa.ForeignKeyConstraint(["scenario_id"], ["viability_scenarios.scenario_id"]),
            sa.PrimaryKeyConstraint("flow_id"),
            sa.UniqueConstraint("scenario_id", "period_start", name="uq_viability_scenario_period"),
        )
        op.create_index("ix_viability_monthly_flow_scenario", "viability_monthly_flows", ["scenario_id", "period_start"])

    if not inspector.has_table("viability_snapshots"):
        op.create_table(
            "viability_snapshots",
            sa.Column("snapshot_id", sa.String(length=36), nullable=False),
            sa.Column("study_id", sa.String(length=36), nullable=False),
            sa.Column("scenario_id", sa.String(length=36), nullable=False),
            sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
            sa.Column("payload_json", sa.JSON(), nullable=False),
            sa.Column("created_by", sa.String(length=36), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.ForeignKeyConstraint(["study_id"], ["viability_studies.study_id"]),
            sa.ForeignKeyConstraint(["scenario_id"], ["viability_scenarios.scenario_id"]),
            sa.ForeignKeyConstraint(["created_by"], ["iam_users.user_id"]),
            sa.PrimaryKeyConstraint("snapshot_id"),
            sa.UniqueConstraint("snapshot_hash", name="uq_viability_snapshot_hash"),
        )
        op.create_index("ix_viability_snapshot_study_created", "viability_snapshots", ["study_id", "created_at"])

    if not inspector.has_table("integration_erp_connections"):
        op.create_table(
            "integration_erp_connections",
            sa.Column("connection_id", sa.String(length=36), nullable=False),
            sa.Column("tenant_id", sa.String(length=36), nullable=False),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("external_tenant", sa.String(length=255), nullable=False),
            sa.Column("scopes", sa.JSON(), nullable=False),
            sa.Column("secret_ciphertext", sa.Text(), nullable=False),
            sa.Column("secret_key_version", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by", sa.String(length=36), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["iam_tenants.tenant_id"]),
            sa.ForeignKeyConstraint(["created_by"], ["iam_users.user_id"]),
            sa.PrimaryKeyConstraint("connection_id"),
            sa.UniqueConstraint("tenant_id", "provider", "external_tenant", name="uq_erp_connection_tenant_provider"),
        )
        op.create_index("ix_erp_connection_tenant_status", "integration_erp_connections", ["tenant_id", "status"])

    if not inspector.has_table("integration_sync_jobs"):
        op.create_table(
            "integration_sync_jobs",
            sa.Column("sync_job_id", sa.String(length=36), nullable=False),
            sa.Column("connection_id", sa.String(length=36), nullable=False),
            sa.Column("tenant_id", sa.String(length=36), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("mode", sa.String(length=32), nullable=False),
            sa.Column("cursor", sa.String(length=255), nullable=True),
            sa.Column("records_seen", sa.Integer(), nullable=False),
            sa.Column("records_imported", sa.Integer(), nullable=False),
            sa.Column("error_code", sa.String(length=64), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["connection_id"], ["integration_erp_connections.connection_id"]),
            sa.ForeignKeyConstraint(["tenant_id"], ["iam_tenants.tenant_id"]),
            sa.PrimaryKeyConstraint("sync_job_id"),
        )
        op.create_index("ix_sync_job_connection_created", "integration_sync_jobs", ["connection_id", "created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table in (
        "integration_sync_jobs",
        "integration_erp_connections",
        "viability_snapshots",
        "viability_monthly_flows",
        "viability_scenarios",
        "viability_studies",
    ):
        if inspector.has_table(table):
            op.drop_table(table)
