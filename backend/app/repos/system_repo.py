from __future__ import annotations

from datetime import datetime

from sqlalchemy import Select, or_, select, text
from sqlalchemy.orm import Session

from app.models.community import BotSpeechConfigRecord, BotSpeechMessageRecord


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

    def list_active_bot_speech_messages(
        self,
        session: Session,
        *,
        now: datetime,
        limit: int = 20,
    ) -> list[BotSpeechMessageRecord]:
        statement: Select[tuple[BotSpeechMessageRecord]] = (
            select(BotSpeechMessageRecord)
            .where(
                BotSpeechMessageRecord.status == "PUBLISHED",
                or_(BotSpeechMessageRecord.starts_at.is_(None), BotSpeechMessageRecord.starts_at <= now),
                or_(BotSpeechMessageRecord.ends_at.is_(None), BotSpeechMessageRecord.ends_at > now),
            )
            .order_by(
                BotSpeechMessageRecord.priority.desc(),
                BotSpeechMessageRecord.starts_at.asc(),
                BotSpeechMessageRecord.created_at.asc(),
                BotSpeechMessageRecord.id.asc(),
            )
            .limit(limit)
        )
        return list(session.scalars(statement))

    def list_bot_speech_messages(self, session: Session, *, limit: int = 100) -> list[BotSpeechMessageRecord]:
        statement = (
            select(BotSpeechMessageRecord)
            .order_by(BotSpeechMessageRecord.created_at.desc(), BotSpeechMessageRecord.id.desc())
            .limit(limit)
        )
        return list(session.scalars(statement))

    def get_bot_speech_message(self, session: Session, message_id: int) -> BotSpeechMessageRecord | None:
        return session.get(BotSpeechMessageRecord, message_id)

    def save_bot_speech_message(
        self,
        session: Session,
        entity: BotSpeechMessageRecord,
    ) -> BotSpeechMessageRecord:
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity
