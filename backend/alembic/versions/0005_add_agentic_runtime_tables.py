"""add durable agentic runtime tables

Revision ID: 0005_add_agentic_runtime_tables
Revises: 0004_contribution_refund_fields
Create Date: 2026-07-26 00:00:00.000000
"""

from __future__ import annotations

revision = "0005_add_agentic_runtime_tables"
down_revision = "0004_contribution_refund_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Retained only to preserve the revision chain after the legacy Agent reset.
    # Existing installations keep their historical tables; fresh installations
    # do not create unused Agent runtime storage.
    pass


def downgrade() -> None:
    # Never drop historical tables from an existing installation implicitly.
    pass
