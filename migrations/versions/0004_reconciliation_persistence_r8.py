"""Persist commission reconciliation inbox/outbox and review queue.

Revision ID: 0004_reconciliation_persistence_r8
Revises: 0003_risk_governance_r7
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_reconciliation_persistence_r8"
down_revision = "0003_risk_governance_r7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    if not inspector.has_table("post_closing_commission_ledger"):
        op.create_table(
            "post_closing_commission_ledger",
            sa.Column("commission_id", sa.String(length=36), nullable=False),
            sa.Column("match_id", sa.String(length=36), nullable=False),
            sa.Column("beneficiary_tenant_id", sa.String(length=36), nullable=False),
            sa.Column("contract_id", sa.String(length=128), nullable=True),
            sa.Column("trigger_event", sa.String(length=128), nullable=False),
            sa.Column("base_amount", sa.Numeric(precision=19, scale=4), nullable=False),
            sa.Column("rate_bps", sa.Integer(), nullable=False),
            sa.Column("estimated_amount", sa.Numeric(precision=19, scale=4), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="ESTIMATE_ONLY"),
            sa.Column("currency", sa.String(length=3), nullable=False, server_default="BRL"),
            sa.Column("metadata", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["match_id"], ["marketplace_matches.match_id"]),
            sa.ForeignKeyConstraint(["beneficiary_tenant_id"], ["iam_tenants.tenant_id"]),
            sa.PrimaryKeyConstraint("commission_id"),
        )
        op.create_index(
            "ix_commission_ledger_beneficiary_status",
            "post_closing_commission_ledger",
            ["beneficiary_tenant_id", "status"],
        )
        op.create_index("ix_commission_ledger_match", "post_closing_commission_ledger", ["match_id"])
        op.create_index("ix_commission_ledger_contract", "post_closing_commission_ledger", ["contract_id"])

    if not inspector.has_table("post_closing_reconciliation_inbox"):
        op.create_table(
            "post_closing_reconciliation_inbox",
            sa.Column("inbox_id", sa.String(length=36), nullable=False),
            sa.Column("source", sa.String(length=128), nullable=False),
            sa.Column("external_event_id", sa.String(length=255), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="RECEIVED"),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("inbox_id"),
            sa.UniqueConstraint("source", "external_event_id", name="uq_reconciliation_inbox_source_event"),
        )
        op.create_index(
            "ix_reconciliation_inbox_status_received",
            "post_closing_reconciliation_inbox",
            ["status", "received_at"],
        )

    if not inspector.has_table("post_closing_reconciliation_outbox"):
        op.create_table(
            "post_closing_reconciliation_outbox",
            sa.Column("outbox_id", sa.String(length=36), nullable=False),
            sa.Column("event_key", sa.String(length=255), nullable=False),
            sa.Column("event_type", sa.String(length=128), nullable=False),
            sa.Column("aggregate_type", sa.String(length=64), nullable=False),
            sa.Column("aggregate_id", sa.String(length=128), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING"),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("outbox_id"),
            sa.UniqueConstraint("event_key", name="uq_reconciliation_outbox_event_key"),
        )
        op.create_index(
            "ix_reconciliation_outbox_status_available",
            "post_closing_reconciliation_outbox",
            ["status", "available_at"],
        )

    if not inspector.has_table("post_closing_reconciliation_links"):
        op.create_table(
            "post_closing_reconciliation_links",
            sa.Column("link_id", sa.String(length=36), nullable=False),
            sa.Column("inbox_id", sa.String(length=36), nullable=False),
            sa.Column("commission_id", sa.String(length=36), nullable=True),
            sa.Column("decision", sa.String(length=32), nullable=False),
            sa.Column("reason", sa.String(length=64), nullable=False),
            sa.Column("amount_variance", sa.Numeric(precision=19, scale=4), nullable=True),
            sa.Column("detail", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["inbox_id"], ["post_closing_reconciliation_inbox.inbox_id"]),
            sa.ForeignKeyConstraint(["commission_id"], ["post_closing_commission_ledger.commission_id"]),
            sa.PrimaryKeyConstraint("link_id"),
            sa.UniqueConstraint("inbox_id", name="uq_reconciliation_link_inbox"),
            sa.UniqueConstraint("commission_id", "inbox_id", name="uq_reconciliation_link_pair"),
        )
        op.create_index("ix_reconciliation_link_commission", "post_closing_reconciliation_links", ["commission_id"])

    if not inspector.has_table("post_closing_reconciliation_reviews"):
        op.create_table(
            "post_closing_reconciliation_reviews",
            sa.Column("review_id", sa.String(length=36), nullable=False),
            sa.Column("inbox_id", sa.String(length=36), nullable=False),
            sa.Column("link_id", sa.String(length=36), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="OPEN"),
            sa.Column("reason", sa.String(length=64), nullable=False),
            sa.Column("expected_amount", sa.Numeric(precision=19, scale=4), nullable=True),
            sa.Column("received_amount", sa.Numeric(precision=19, scale=4), nullable=False),
            sa.Column("amount_variance", sa.Numeric(precision=19, scale=4), nullable=True),
            sa.Column("currency", sa.String(length=3), nullable=False, server_default="BRL"),
            sa.Column("assigned_to", sa.String(length=36), nullable=True),
            sa.Column("decision", sa.String(length=32), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["inbox_id"], ["post_closing_reconciliation_inbox.inbox_id"]),
            sa.ForeignKeyConstraint(["link_id"], ["post_closing_reconciliation_links.link_id"]),
            sa.ForeignKeyConstraint(["assigned_to"], ["iam_users.user_id"]),
            sa.PrimaryKeyConstraint("review_id"),
            sa.UniqueConstraint("inbox_id", name="uq_reconciliation_review_inbox"),
        )
        op.create_index(
            "ix_reconciliation_review_status_due",
            "post_closing_reconciliation_reviews",
            ["status", "due_at"],
        )
        op.create_index(
            "ix_reconciliation_review_assignee",
            "post_closing_reconciliation_reviews",
            ["assigned_to", "status"],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    if inspector.has_table("post_closing_reconciliation_reviews"):
        op.drop_index("ix_reconciliation_review_assignee", table_name="post_closing_reconciliation_reviews")
        op.drop_index("ix_reconciliation_review_status_due", table_name="post_closing_reconciliation_reviews")
        op.drop_table("post_closing_reconciliation_reviews")

    if inspector.has_table("post_closing_reconciliation_links"):
        op.drop_index("ix_reconciliation_link_commission", table_name="post_closing_reconciliation_links")
        op.drop_table("post_closing_reconciliation_links")

    if inspector.has_table("post_closing_reconciliation_outbox"):
        op.drop_index("ix_reconciliation_outbox_status_available", table_name="post_closing_reconciliation_outbox")
        op.drop_table("post_closing_reconciliation_outbox")

    if inspector.has_table("post_closing_reconciliation_inbox"):
        op.drop_index("ix_reconciliation_inbox_status_received", table_name="post_closing_reconciliation_inbox")
        op.drop_table("post_closing_reconciliation_inbox")

    if inspector.has_table("post_closing_commission_ledger"):
        op.drop_index("ix_commission_ledger_contract", table_name="post_closing_commission_ledger")
        op.drop_index("ix_commission_ledger_match", table_name="post_closing_commission_ledger")
        op.drop_index("ix_commission_ledger_beneficiary_status", table_name="post_closing_commission_ledger")
        op.drop_table("post_closing_commission_ledger")
