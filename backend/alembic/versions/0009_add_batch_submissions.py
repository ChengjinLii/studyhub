"""Add bulk submission records without changing existing tables or data."""

from alembic import op

from app.models.batch_submissions import (
    BatchAuditRecord,
    BatchPublicationRecord,
    BatchSubmissionItemRecord,
    BatchSubmissionRecord,
)


revision = "0009_batch_submission_records_and_audits"
down_revision = "0008_material_submission_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    for model in (BatchSubmissionRecord, BatchSubmissionItemRecord, BatchPublicationRecord, BatchAuditRecord):
        model.__table__.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    # Preserve submission receipts and audit data across application rollbacks.
    pass
