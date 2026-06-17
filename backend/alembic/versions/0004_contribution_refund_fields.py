"""add refund tracking fields to material_request_contributions

Revision ID: 0004_contribution_refund_fields
Revises: 0003_settlement_transfer_binding
Create Date: 2026-06-16 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0004_contribution_refund_fields"
down_revision = "0003_settlement_transfer_binding"
branch_labels = None
depends_on = None

TABLE = "material_request_contributions"
COLUMNS = [
    ("refund_status", sa.String(32)),
    ("refund_trade_no", sa.String(64)),
    ("refunded_at", sa.DateTime(timezone=True)),
]


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {col["name"] for col in inspector.get_columns(TABLE)}
    for name, col_type in COLUMNS:
        if name not in existing:
            op.add_column(TABLE, sa.Column(name, col_type, nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {col["name"] for col in inspector.get_columns(TABLE)}
    for name, _ in COLUMNS:
        if name in existing:
            op.drop_column(TABLE, name)
