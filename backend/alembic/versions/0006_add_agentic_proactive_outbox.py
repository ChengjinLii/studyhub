"""add durable proactive agent event outbox

Revision ID: 0006_add_agentic_proactive_outbox
Revises: 0005_add_agentic_runtime_tables
Create Date: 2026-07-26 00:00:00.000000
"""

from __future__ import annotations

revision = "0006_add_agentic_proactive_outbox"
down_revision = "0005_add_agentic_runtime_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Retained only to preserve the revision chain after the legacy Agent reset.
    pass


def downgrade() -> None:
    # Never drop historical tables from an existing installation implicitly.
    pass
