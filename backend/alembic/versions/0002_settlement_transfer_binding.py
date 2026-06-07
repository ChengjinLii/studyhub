"""add settlements.payout_transfer_id for transfer-settlement binding

Revision ID: 0002_settlement_transfer_binding
Revises: 0001_baseline_schema
Create Date: 2026-06-07 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0002_settlement_transfer_binding"
down_revision = "0001_baseline_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("settlements", sa.Column("payout_transfer_id", sa.Integer(), nullable=True))
    op.create_index("ix_settlements_payout_transfer_id", "settlements", ["payout_transfer_id"])


def downgrade() -> None:
    op.drop_index("ix_settlements_payout_transfer_id", table_name="settlements")
    op.drop_column("settlements", "payout_transfer_id")
