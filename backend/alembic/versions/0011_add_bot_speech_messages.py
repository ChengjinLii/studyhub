"""Add queued, scheduled floating bot speech messages."""

from alembic import op

from app.models.community import BotSpeechMessageRecord


revision = "0011_add_queued_bot_speech_messages"
down_revision = "0010_bot_speech_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    BotSpeechMessageRecord.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    # Keep administrator messages and their audit trail across application rollbacks.
    pass
