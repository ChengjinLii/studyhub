"""baseline schema

Revision ID: 0001_baseline_schema
Revises:
Create Date: 2026-05-17 00:00:00.000000
"""

from __future__ import annotations

from alembic import op

from app.models import Base


revision = "0001_baseline_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
