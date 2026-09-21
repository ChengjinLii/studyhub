"""Add the administrator-managed floating bot speech configuration."""

from alembic import op

from app.models.community import BotSpeechConfigRecord


revision = "0010_bot_speech_config"
down_revision = "0009_batch_submission_records_and_audits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    BotSpeechConfigRecord.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    # Preserve the current site message across application rollbacks.
    pass
