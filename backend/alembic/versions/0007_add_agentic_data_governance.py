"""add agentic data-governance provenance

Revision ID: 0007_add_agentic_data_governance
Revises: 0006_add_agentic_proactive_outbox
Create Date: 2026-07-27 00:00:00.000000

This migration is intentionally explicit.  It does not import ORM metadata,
which keeps deployed schema changes independent from whatever model definition
the application process happens to load.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0007_add_agentic_data_governance"
down_revision = "0006_add_agentic_proactive_outbox"
branch_labels = None
depends_on = None


_ARTIFACT_COLUMNS = (
    sa.Column("training_allowed", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    sa.Column("sensitivity", sa.String(length=32), nullable=False, server_default="internal"),
    sa.Column("license_class", sa.String(length=64), nullable=False, server_default="internal_eval_only"),
    sa.Column("source_scope", sa.String(length=32), nullable=False, server_default="internal"),
    sa.Column("contains_personal_data", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    sa.Column("anonymization_version", sa.String(length=128), nullable=True),
    sa.Column(
        "retention_policy",
        sa.String(length=256),
        nullable=False,
        server_default="internal_evaluation_only",
    ),
)


def upgrade() -> None:
    if _has_table("agent_artifacts"):
        for column in _ARTIFACT_COLUMNS:
            if not _has_column("agent_artifacts", column.name):
                op.add_column("agent_artifacts", column)
    if _has_table("agent_steps") and not _has_column("agent_steps", "state_group_key_v2"):
        op.add_column("agent_steps", sa.Column("state_group_key_v2", sa.String(length=256), nullable=True))


def downgrade() -> None:
    # Classification is provenance for already-created data.  Do not erase it
    # on a production downgrade merely to restore an older binary.
    pass


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))
