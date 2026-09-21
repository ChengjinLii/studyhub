from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.community import BotSpeechConfigRecord


class SystemRepository:
    def ping(self, session: Session) -> bool:
        session.execute(text("SELECT 1"))
        return True

    def get_bot_speech_config(self, session: Session) -> BotSpeechConfigRecord | None:
        return session.get(BotSpeechConfigRecord, 1)

    def save_bot_speech_config(
        self,
        session: Session,
        entity: BotSpeechConfigRecord,
    ) -> BotSpeechConfigRecord:
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity
