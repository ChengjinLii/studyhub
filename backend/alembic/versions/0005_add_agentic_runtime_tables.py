"""add durable agentic runtime tables

Revision ID: 0005_add_agentic_runtime_tables
Revises: 0004_contribution_refund_fields
Create Date: 2026-07-26 00:00:00.000000
"""

from __future__ import annotations

from alembic import op

from app.models.agentic_runtime import (
    AgentArtifactRecord,
    AgentJobRecord,
    AgentRunRecord,
    AgentStepRecord,
    AgentThreadRecord,
    AgentWaitRecord,
)


revision = "0005_add_agentic_runtime_tables"
down_revision = "0004_contribution_refund_fields"
branch_labels = None
depends_on = None


RUNTIME_TABLES = (
    AgentThreadRecord.__table__,
    AgentRunRecord.__table__,
    AgentStepRecord.__table__,
    AgentWaitRecord.__table__,
    AgentJobRecord.__table__,
    AgentArtifactRecord.__table__,
)


def upgrade() -> None:
    # 0001 calls Base.metadata.create_all(), so fresh installs may already have
    # these tables. checkfirst makes both fresh and upgraded databases converge.
    bind = op.get_bind()
    for table in RUNTIME_TABLES:
        table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    # This revision owns only new agentic tables. Reversing it leaves all legacy
    # StudyHub tables untouched while providing a real up/down migration pair.
    bind = op.get_bind()
    for table in reversed(RUNTIME_TABLES):
        table.drop(bind=bind, checkfirst=True)
