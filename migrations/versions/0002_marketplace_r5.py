"""Marketplace bilateral R5.

Revision ID: 0002_marketplace_r5
Revises: 0001_greenfield_foundation
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_marketplace_r5"
down_revision = "0001_greenfield_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The legacy 0001 migration creates the full SQLAlchemy metadata on a fresh
    # database. On an existing 0001 database the R5 tables are absent and must
    # be created here. Keep this guard for both paths.
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("marketplace_borrower_profiles"):
        return

    op.create_table(
        "marketplace_borrower_profiles",
        sa.Column("borrower_profile_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("iam_tenants.tenant_id"), nullable=False),
        sa.Column("segment", sa.String(64), nullable=False),
        sa.Column("sectors", sa.JSON(), nullable=False),
        sa.Column("regions", sa.JSON(), nullable=False),
        sa.Column("group_profile", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("iam_users.user_id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", name="uq_borrower_profile_tenant"),
    )
    op.create_index("ix_marketplace_borrower_profiles_tenant_id", "marketplace_borrower_profiles", ["tenant_id"])

    op.create_table(
        "marketplace_funding_providers",
        sa.Column("funding_provider_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("iam_tenants.tenant_id"), nullable=False),
        sa.Column("provider_type", sa.String(32), nullable=False),
        sa.Column("legal_name", sa.String(255), nullable=False),
        sa.Column("website", sa.String(512), nullable=True),
        sa.Column("mandate_summary", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("iam_users.user_id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", name="uq_funding_provider_tenant"),
    )
    op.create_index("ix_marketplace_funding_providers_tenant_id", "marketplace_funding_providers", ["tenant_id"])

    op.create_table(
        "marketplace_funding_products",
        sa.Column("funding_product_id", sa.String(36), primary_key=True),
        sa.Column("funding_provider_id", sa.String(36), sa.ForeignKey("marketplace_funding_providers.funding_provider_id"), nullable=False),
        sa.Column("provider_tenant_id", sa.String(36), sa.ForeignKey("iam_tenants.tenant_id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("product_type", sa.String(64), nullable=False),
        sa.Column("min_ticket", sa.Numeric(19, 4), nullable=False),
        sa.Column("max_ticket", sa.Numeric(19, 4), nullable=False),
        sa.Column("min_term_months", sa.Integer(), nullable=False),
        sa.Column("max_term_months", sa.Integer(), nullable=False),
        sa.Column("allowed_collateral_types", sa.JSON(), nullable=False),
        sa.Column("sectors", sa.JSON(), nullable=False),
        sa.Column("regions", sa.JSON(), nullable=False),
        sa.Column("stage_requirements", sa.JSON(), nullable=False),
        sa.Column("indicative_terms", sa.JSON(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("iam_users.user_id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_funding_product_status", "marketplace_funding_products", ["status"])
    op.create_index("ix_funding_product_provider", "marketplace_funding_products", ["funding_provider_id"])
    op.create_index("ix_marketplace_funding_products_provider_tenant_id", "marketplace_funding_products", ["provider_tenant_id"])

    op.create_table(
        "marketplace_partner_profiles",
        sa.Column("partner_profile_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("iam_tenants.tenant_id"), nullable=False),
        sa.Column("partner_type", sa.String(64), nullable=False),
        sa.Column("focus_regions", sa.JSON(), nullable=False),
        sa.Column("commercial_terms", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("iam_users.user_id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", name="uq_partner_profile_tenant"),
    )
    op.create_index("ix_marketplace_partner_profiles_tenant_id", "marketplace_partner_profiles", ["tenant_id"])

    op.create_table(
        "marketplace_credit_requests",
        sa.Column("credit_request_id", sa.String(36), primary_key=True),
        sa.Column("owner_tenant_id", sa.String(36), sa.ForeignKey("iam_tenants.tenant_id"), nullable=False),
        sa.Column("borrower_profile_id", sa.String(36), sa.ForeignKey("marketplace_borrower_profiles.borrower_profile_id"), nullable=False),
        sa.Column("source_partner_tenant_id", sa.String(36), sa.ForeignKey("iam_tenants.tenant_id"), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("credit_type", sa.String(64), nullable=False),
        sa.Column("requested_amount", sa.Numeric(19, 4), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("term_months", sa.Integer(), nullable=False),
        sa.Column("grace_months", sa.Integer(), nullable=False),
        sa.Column("collateral_types", sa.JSON(), nullable=False),
        sa.Column("sectors", sa.JSON(), nullable=False),
        sa.Column("regions", sa.JSON(), nullable=False),
        sa.Column("project_stage", sa.String(64), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("consent_status", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("iam_users.user_id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_credit_request_owner_status", "marketplace_credit_requests", ["owner_tenant_id", "status"])
    op.create_index("ix_credit_request_partner", "marketplace_credit_requests", ["source_partner_tenant_id"])

    op.create_table(
        "marketplace_credit_request_documents",
        sa.Column("credit_request_document_id", sa.String(36), primary_key=True),
        sa.Column("credit_request_id", sa.String(36), sa.ForeignKey("marketplace_credit_requests.credit_request_id"), nullable=False),
        sa.Column("owner_tenant_id", sa.String(36), sa.ForeignKey("iam_tenants.tenant_id"), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("document_type", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("checksum_sha256", sa.String(64), nullable=False),
        sa.Column("processing_status", sa.String(32), nullable=False),
        sa.Column("uploaded_by", sa.String(36), sa.ForeignKey("iam_users.user_id"), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_credit_request_document_request", "marketplace_credit_request_documents", ["credit_request_id"])

    op.create_table(
        "marketplace_matches",
        sa.Column("match_id", sa.String(36), primary_key=True),
        sa.Column("credit_request_id", sa.String(36), sa.ForeignKey("marketplace_credit_requests.credit_request_id"), nullable=False),
        sa.Column("funding_product_id", sa.String(36), sa.ForeignKey("marketplace_funding_products.funding_product_id"), nullable=False),
        sa.Column("borrower_tenant_id", sa.String(36), sa.ForeignKey("iam_tenants.tenant_id"), nullable=False),
        sa.Column("funder_tenant_id", sa.String(36), sa.ForeignKey("iam_tenants.tenant_id"), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("eligible", sa.Boolean(), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("gaps", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("assigned_agent_id", sa.String(36), sa.ForeignKey("iam_users.user_id"), nullable=True),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("iam_users.user_id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("credit_request_id", "funding_product_id", name="uq_match_request_product"),
    )
    op.create_index("ix_match_funder_status", "marketplace_matches", ["funder_tenant_id", "status"])
    op.create_index("ix_match_agent_status", "marketplace_matches", ["assigned_agent_id", "status"])

    op.create_table(
        "marketplace_match_events",
        sa.Column("match_event_id", sa.String(36), primary_key=True),
        sa.Column("match_id", sa.String(36), sa.ForeignKey("marketplace_matches.match_id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("iam_users.user_id"), nullable=False),
        sa.Column("visibility", sa.String(32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_marketplace_match_events_match_id", "marketplace_match_events", ["match_id"])

    op.create_table(
        "marketplace_commission_events",
        sa.Column("commission_event_id", sa.String(36), primary_key=True),
        sa.Column("match_id", sa.String(36), sa.ForeignKey("marketplace_matches.match_id"), nullable=False),
        sa.Column("beneficiary_tenant_id", sa.String(36), sa.ForeignKey("iam_tenants.tenant_id"), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("base_amount", sa.Numeric(19, 4), nullable=False),
        sa.Column("rate_bps", sa.Integer(), nullable=False),
        sa.Column("estimated_amount", sa.Numeric(19, 4), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("iam_users.user_id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_marketplace_commission_events_match_id", "marketplace_commission_events", ["match_id"])


def downgrade() -> None:
    op.drop_index("ix_marketplace_commission_events_match_id", table_name="marketplace_commission_events")
    op.drop_table("marketplace_commission_events")
    op.drop_index("ix_marketplace_match_events_match_id", table_name="marketplace_match_events")
    op.drop_table("marketplace_match_events")
    op.drop_index("ix_match_agent_status", table_name="marketplace_matches")
    op.drop_index("ix_match_funder_status", table_name="marketplace_matches")
    op.drop_table("marketplace_matches")
    op.drop_index("ix_credit_request_document_request", table_name="marketplace_credit_request_documents")
    op.drop_table("marketplace_credit_request_documents")
    op.drop_index("ix_credit_request_partner", table_name="marketplace_credit_requests")
    op.drop_index("ix_credit_request_owner_status", table_name="marketplace_credit_requests")
    op.drop_table("marketplace_credit_requests")
    op.drop_index("ix_marketplace_partner_profiles_tenant_id", table_name="marketplace_partner_profiles")
    op.drop_table("marketplace_partner_profiles")
    op.drop_index("ix_marketplace_funding_products_provider_tenant_id", table_name="marketplace_funding_products")
    op.drop_index("ix_funding_product_provider", table_name="marketplace_funding_products")
    op.drop_index("ix_funding_product_status", table_name="marketplace_funding_products")
    op.drop_table("marketplace_funding_products")
    op.drop_index("ix_marketplace_funding_providers_tenant_id", table_name="marketplace_funding_providers")
    op.drop_table("marketplace_funding_providers")
    op.drop_index("ix_marketplace_borrower_profiles_tenant_id", table_name="marketplace_borrower_profiles")
    op.drop_table("marketplace_borrower_profiles")
