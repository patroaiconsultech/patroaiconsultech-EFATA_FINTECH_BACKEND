"""Link ERP sync jobs to viability studies.

Revision ID: 0009_sync_job_study_link_r11
Revises: 0008_erp_connector_runtime_r11
"""

import sqlalchemy as sa
from alembic import op

revision = "0009_sync_job_study_link_r11"
down_revision = "0008_erp_connector_runtime_r11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("integration_sync_jobs"):
        return

    columns = {
        column["name"]
        for column in inspector.get_columns("integration_sync_jobs")
    }
    if "study_id" not in columns:
        study_column = sa.Column("study_id", sa.String(length=36), nullable=True)
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table(
                "integration_sync_jobs",
                recreate="always",
            ) as batch_op:
                batch_op.add_column(study_column)
                batch_op.create_foreign_key(
                    "fk_sync_job_study",
                    "viability_studies",
                    ["study_id"],
                    ["study_id"],
                )
        else:
            op.add_column("integration_sync_jobs", study_column)
            op.create_foreign_key(
                "fk_sync_job_study",
                "integration_sync_jobs",
                "viability_studies",
                ["study_id"],
                ["study_id"],
            )

    inspector = sa.inspect(bind)
    index_names = {
        index["name"]
        for index in inspector.get_indexes("integration_sync_jobs")
        if index.get("name")
    }
    if "ix_sync_job_study_created" not in index_names:
        op.create_index(
            "ix_sync_job_study_created",
            "integration_sync_jobs",
            ["study_id", "created_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("integration_sync_jobs"):
        return

    columns = {
        column["name"]
        for column in inspector.get_columns("integration_sync_jobs")
    }
    if "study_id" not in columns:
        return

    index_names = {
        index["name"]
        for index in inspector.get_indexes("integration_sync_jobs")
        if index.get("name")
    }
    if "ix_sync_job_study_created" in index_names:
        op.drop_index(
            "ix_sync_job_study_created",
            table_name="integration_sync_jobs",
        )

    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(
            "integration_sync_jobs",
            recreate="always",
        ) as batch_op:
            batch_op.drop_column("study_id")
    else:
        op.drop_constraint(
            "fk_sync_job_study",
            "integration_sync_jobs",
            type_="foreignkey",
        )
        op.drop_column("integration_sync_jobs", "study_id")
