"""Persist immutable Consent Ledger and observable outbox leases.

Revision ID: 0005_consent_ledger_observability_r10
Revises: 0004_reconciliation_persistence_r8
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_consent_ledger_observability_r10"
down_revision = "0004_reconciliation_persistence_r8"
branch_labels = None
depends_on = None


def _has_column(inspector: sa.Inspector, table: str, column: str) -> bool:
    return any(item["name"] == column for item in inspector.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    outbox = "post_closing_reconciliation_outbox"
    if inspector.has_table(outbox):
        additions = (
            ("claimed_at", sa.DateTime(timezone=True)),
            ("lease_until", sa.DateTime(timezone=True)),
            ("last_attempt_at", sa.DateTime(timezone=True)),
            ("failed_at", sa.DateTime(timezone=True)),
            ("dead_lettered_at", sa.DateTime(timezone=True)),
        )
        for name, column_type in additions:
            if not _has_column(inspector, outbox, name):
                op.add_column(outbox, sa.Column(name, column_type, nullable=True))

    if not inspector.has_table("consent_ledger_heads"):
        op.create_table(
            "consent_ledger_heads",
            sa.Column("tenant_id", sa.String(length=36), nullable=False),
            sa.Column("last_sequence", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("last_hash", sa.String(length=64), nullable=False, server_default="GENESIS"),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["iam_tenants.tenant_id"]),
            sa.PrimaryKeyConstraint("tenant_id"),
        )

    if not inspector.has_table("consent_ledger_grants"):
        op.create_table(
            "consent_ledger_grants",
            sa.Column("consent_id", sa.String(length=36), nullable=False),
            sa.Column("tenant_id", sa.String(length=36), nullable=False),
            sa.Column("subject_ref", sa.String(length=128), nullable=False),
            sa.Column("purpose", sa.String(length=128), nullable=False),
            sa.Column("scopes", sa.JSON(), nullable=False),
            sa.Column("recipient", sa.String(length=255), nullable=False),
            sa.Column("source_institution", sa.String(length=255), nullable=False),
            sa.Column("provider_reference", sa.String(length=255), nullable=True),
            sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="ACTIVE"),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False),
            sa.Column("created_by", sa.String(length=36), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["iam_tenants.tenant_id"]),
            sa.ForeignKeyConstraint(["created_by"], ["iam_users.user_id"]),
            sa.PrimaryKeyConstraint("consent_id"),
        )
        op.create_index(
            "ix_consent_grant_subject_status",
            "consent_ledger_grants",
            ["tenant_id", "subject_ref", "status"],
        )
        op.create_index("ix_consent_grant_expiry", "consent_ledger_grants", ["status", "expires_at"])

    if not inspector.has_table("consent_ledger_events"):
        op.create_table(
            "consent_ledger_events",
            sa.Column("event_id", sa.String(length=36), nullable=False),
            sa.Column("tenant_id", sa.String(length=36), nullable=False),
            sa.Column("consent_id", sa.String(length=36), nullable=True),
            sa.Column("sequence_no", sa.BigInteger(), nullable=False),
            sa.Column("event_type", sa.String(length=64), nullable=False),
            sa.Column("actor_id", sa.String(length=36), nullable=False),
            sa.Column("purpose", sa.String(length=128), nullable=False),
            sa.Column("scopes", sa.JSON(), nullable=False),
            sa.Column("request_id", sa.String(length=36), nullable=False),
            sa.Column("correlation_id", sa.String(length=36), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("payload_hash", sa.String(length=64), nullable=False),
            sa.Column("previous_hash", sa.String(length=64), nullable=False),
            sa.Column("event_hash", sa.String(length=64), nullable=False),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["iam_tenants.tenant_id"]),
            sa.ForeignKeyConstraint(["consent_id"], ["consent_ledger_grants.consent_id"]),
            sa.PrimaryKeyConstraint("event_id"),
            sa.UniqueConstraint("tenant_id", "sequence_no", name="uq_consent_ledger_tenant_sequence"),
            sa.UniqueConstraint("event_hash", name="uq_consent_ledger_event_hash"),
        )
        op.create_index(
            "ix_consent_ledger_consent_time",
            "consent_ledger_events",
            ["consent_id", "occurred_at"],
        )
        op.create_index(
            "ix_consent_ledger_type_time",
            "consent_ledger_events",
            ["event_type", "occurred_at"],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    if inspector.has_table("consent_ledger_events"):
        op.drop_index("ix_consent_ledger_type_time", table_name="consent_ledger_events")
        op.drop_index("ix_consent_ledger_consent_time", table_name="consent_ledger_events")
        op.drop_table("consent_ledger_events")

    if inspector.has_table("consent_ledger_grants"):
        op.drop_index("ix_consent_grant_expiry", table_name="consent_ledger_grants")
        op.drop_index("ix_consent_grant_subject_status", table_name="consent_ledger_grants")
        op.drop_table("consent_ledger_grants")

    if inspector.has_table("consent_ledger_heads"):
        op.drop_table("consent_ledger_heads")

    outbox = "post_closing_reconciliation_outbox"
    if inspector.has_table(outbox):
        for name in ("dead_lettered_at", "failed_at", "last_attempt_at", "lease_until", "claimed_at"):
            if _has_column(sa.inspect(op.get_bind()), outbox, name):
                op.drop_column(outbox, name)
