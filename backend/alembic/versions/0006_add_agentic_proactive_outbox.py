"""add durable proactive agent event outbox

Revision ID: 0006_add_agentic_proactive_outbox
Revises: 0005_add_agentic_runtime_tables
Create Date: 2026-07-26 00:00:00.000000
"""

from __future__ import annotations

from alembic import op

from app.models.agentic_runtime import AgentOutboxRecord


revision = "0006_add_agentic_proactive_outbox"
down_revision = "0005_add_agentic_runtime_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Fresh local installations may already receive the table through
    # Base.metadata.create_all(); checkfirst keeps upgrades idempotent.
    AgentOutboxRecord.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    AgentOutboxRecord.__table__.drop(bind=op.get_bind(), checkfirst=True)
