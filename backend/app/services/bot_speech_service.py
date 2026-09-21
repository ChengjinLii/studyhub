from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.community import BotSpeechConfigRecord
from app.repos.system_repo import SystemRepository
from app.schemas.bot_speech import BotSpeechUpdatePayload
from app.services.read_support import serialize_datetime


class BotSpeechService:
    def __init__(self, system_repo: SystemRepository) -> None:
        self.system_repo = system_repo

    def get_config(self, session: Session) -> dict[str, object]:
        entity = self.system_repo.get_bot_speech_config(session)
        if entity is None:
            return {"enabled": False, "message": "", "updatedAt": None}
        return self._serialize(entity)

    def update_config(
        self,
        session: Session,
        *,
        admin_user_id: int,
        payload: BotSpeechUpdatePayload,
    ) -> dict[str, object]:
        message = payload.message.strip()
        if payload.enabled and not message:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="启用气泡时台词不能为空")

        entity = self.system_repo.get_bot_speech_config(session)
        if entity is None:
            entity = BotSpeechConfigRecord(id=1)
        entity.enabled = payload.enabled
        entity.message = message
        entity.updated_by_user_id = admin_user_id
        self.system_repo.save_bot_speech_config(session, entity)
        session.commit()
        return self._serialize(entity)

    def _serialize(self, entity: BotSpeechConfigRecord) -> dict[str, object]:
        return {
            "enabled": entity.enabled,
            "message": entity.message,
            "updatedAt": serialize_datetime(entity.updated_at),
        }
