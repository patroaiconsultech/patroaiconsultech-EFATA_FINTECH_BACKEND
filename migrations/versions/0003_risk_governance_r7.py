"""Credit risk assessments and human governance reviews R7.

Revision ID: 0003_risk_governance_r7
Revises: 0002_marketplace_r5
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_risk_governance_r7"
down_revision = "0002_marketplace_r5"
branch_labels = None
depends_on = None


def _index_names(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return set()
    return {
        index["name"]
        for index in inspector.get_indexes(table_name)
        if index.get("name")
    }


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    if not inspector.has_table("marketplace_risk_assessments"):
        op.create_table(
            "marketplace_risk_assessments",
            sa.Column("assessment_id", sa.String(36), primary_key=True),
            sa.Column(
                "credit_request_id",
                sa.String(36),
                sa.ForeignKey("marketplace_credit_requests.credit_request_id"),
                nullable=True,
            ),
            sa.Column("policy_version", sa.String(64), nullable=False),
            sa.Column("decision", sa.String(48), nullable=False),
            sa.Column("risk_band", sa.String(32), nullable=False),
            sa.Column("score", sa.Integer(), nullable=False),
            sa.Column("recommendation", sa.Text(), nullable=False),
            sa.Column("rule_results", sa.JSON(), nullable=False),
            sa.Column("evidence", sa.JSON(), nullable=False),
            sa.Column("missing_data", sa.JSON(), nullable=False),
            sa.Column("hard_flags", sa.JSON(), nullable=False),
            sa.Column("soft_flags", sa.JSON(), nullable=False),
            sa.Column("human_status", sa.String(32), nullable=False),
            sa.Column(
                "created_by",
                sa.String(36),
                sa.ForeignKey("iam_users.user_id"),
                nullable=False,
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )

    risk_indexes = _index_names("marketplace_risk_assessments")
    if "ix_marketplace_risk_assessments_credit_request_id" not in risk_indexes:
        op.create_index(
            "ix_marketplace_risk_assessments_credit_request_id",
            "marketplace_risk_assessments",
            ["credit_request_id"],
        )
    if "ix_risk_assessment_request_created" not in risk_indexes:
        op.create_index(
            "ix_risk_assessment_request_created",
            "marketplace_risk_assessments",
            ["credit_request_id", "created_at"],
        )
    if "ix_risk_assessment_decision" not in risk_indexes:
        op.create_index(
            "ix_risk_assessment_decision",
            "marketplace_risk_assessments",
            ["decision", "human_status"],
        )

    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("marketplace_match_governance_reviews"):
        op.create_table(
            "marketplace_match_governance_reviews",
            sa.Column("review_id", sa.String(36), primary_key=True),
            sa.Column(
                "match_id",
                sa.String(36),
                sa.ForeignKey("marketplace_matches.match_id"),
                nullable=False,
            ),
            sa.Column(
                "assessment_id",
                sa.String(36),
                sa.ForeignKey("marketplace_risk_assessments.assessment_id"),
                nullable=True,
            ),
            sa.Column("decision", sa.String(48), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column(
                "actor_id",
                sa.String(36),
                sa.ForeignKey("iam_users.user_id"),
                nullable=False,
            ),
            sa.Column("visibility", sa.String(32), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )

    governance_indexes = _index_names("marketplace_match_governance_reviews")
    if "ix_marketplace_match_governance_reviews_match_id" not in governance_indexes:
        op.create_index(
            "ix_marketplace_match_governance_reviews_match_id",
            "marketplace_match_governance_reviews",
            ["match_id"],
        )
    if "ix_governance_review_match_created" not in governance_indexes:
        op.create_index(
            "ix_governance_review_match_created",
            "marketplace_match_governance_reviews",
            ["match_id", "created_at"],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    if inspector.has_table("marketplace_match_governance_reviews"):
        indexes = _index_names("marketplace_match_governance_reviews")
        if "ix_governance_review_match_created" in indexes:
            op.drop_index(
                "ix_governance_review_match_created",
                table_name="marketplace_match_governance_reviews",
            )
        indexes = _index_names("marketplace_match_governance_reviews")
        if "ix_marketplace_match_governance_reviews_match_id" in indexes:
            op.drop_index(
                "ix_marketplace_match_governance_reviews_match_id",
                table_name="marketplace_match_governance_reviews",
            )
        op.drop_table("marketplace_match_governance_reviews")

    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("marketplace_risk_assessments"):
        indexes = _index_names("marketplace_risk_assessments")
        for index_name in (
            "ix_risk_assessment_decision",
            "ix_risk_assessment_request_created",
            "ix_marketplace_risk_assessments_credit_request_id",
        ):
            if index_name in indexes:
                op.drop_index(
                    index_name,
                    table_name="marketplace_risk_assessments",
                )
                indexes = _index_names("marketplace_risk_assessments")
        op.drop_table("marketplace_risk_assessments")
