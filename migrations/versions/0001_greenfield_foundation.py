"""Greenfield foundation.

Revision ID: 0001_greenfield_foundation
Revises:
"""

from alembic import op

from app.db import Base
from app import models  # noqa: F401

revision = "0001_greenfield_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Initial bootstrap only. Subsequent migrations must use explicit operations.
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
