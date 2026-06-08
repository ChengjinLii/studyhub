"""add settlements.payout_transfer_id for transfer-settlement binding

Revision ID: 0003_settlement_transfer_binding
Revises: 0002_add_market_source_and_order_uploader
Create Date: 2026-06-07 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0003_settlement_transfer_binding"
down_revision = "0002_add_market_source_and_order_uploader"
branch_labels = None
depends_on = None


INDEX_NAME = "ix_settlements_payout_transfer_id"


def upgrade() -> None:
    # The baseline migration (0001) calls Base.metadata.create_all(), which already
    # includes payout_transfer_id once the model declares it. Guard add_column/create_index
    # so a fresh `alembic upgrade head` converges with create_all-built schemas instead of
    # failing on a duplicate column.
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("settlements")}
    if "payout_transfer_id" not in columns:
        op.add_column("settlements", sa.Column("payout_transfer_id", sa.Integer(), nullable=True))
    indexes = {index["name"] for index in inspector.get_indexes("settlements")}
    if INDEX_NAME not in indexes:
        op.create_index(INDEX_NAME, "settlements", ["payout_transfer_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    indexes = {index["name"] for index in inspector.get_indexes("settlements")}
    if INDEX_NAME in indexes:
        op.drop_index(INDEX_NAME, table_name="settlements")
    columns = {column["name"] for column in inspector.get_columns("settlements")}
    if "payout_transfer_id" in columns:
        op.drop_column("settlements", "payout_transfer_id")
