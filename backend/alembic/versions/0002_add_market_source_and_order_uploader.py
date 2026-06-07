"""add market source and order uploader fields

Revision ID: 0002_add_market_source_and_order_uploader
Revises: 0001_baseline_schema
Create Date: 2026-06-08 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_add_market_source_and_order_uploader"
down_revision = "0001_baseline_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if _has_table("market_items") and not _has_column("market_items", "source"):
        op.add_column(
            "market_items",
            sa.Column("source", sa.String(length=16), nullable=False, server_default="local"),
        )

    if _has_table("orders") and not _has_column("orders", "uploader_id"):
        op.add_column("orders", sa.Column("uploader_id", sa.Integer(), nullable=True))

    if _has_table("orders") and _has_column("orders", "uploader_id") and not _has_index("orders", "ix_orders_uploader_id"):
        op.create_index("ix_orders_uploader_id", "orders", ["uploader_id"])


def downgrade() -> None:
    # Production downgrades must not delete fields added to preserve existing user data.
    pass


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))


def _has_index(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))
