"""add idempotency key for material submissions

Revision ID: 0008_material_submission_idempotency
Revises: 0007_add_agentic_data_governance
Create Date: 2026-07-31 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0008_material_submission_idempotency"
down_revision = "0007_add_agentic_data_governance"
branch_labels = None
depends_on = None


INDEX_NAME = "uq_materials_uploader_submission_key"


def upgrade() -> None:
    if not _has_table("materials"):
        return
    if not _has_column("materials", "submission_key"):
        op.add_column("materials", sa.Column("submission_key", sa.String(length=64), nullable=True))
    if not _has_unique_index("materials", INDEX_NAME):
        op.create_index(
            INDEX_NAME,
            "materials",
            ["uploader_id", "submission_key"],
            unique=True,
        )


def downgrade() -> None:
    # Submission receipts protect users from duplicate material records. Preserve
    # them across application rollbacks rather than deleting production data.
    pass


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(table_name: str) -> bool:
    return table_name in _inspector().get_table_names()


def _has_column(table_name: str, column_name: str) -> bool:
    return any(column["name"] == column_name for column in _inspector().get_columns(table_name))


def _has_unique_index(table_name: str, index_name: str) -> bool:
    inspector = _inspector()
    indexes = inspector.get_indexes(table_name)
    constraints = inspector.get_unique_constraints(table_name)
    return any(item.get("name") == index_name for item in [*indexes, *constraints])
