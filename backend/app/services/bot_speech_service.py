from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.community import BotSpeechConfigRecord, BotSpeechMessageRecord
from app.repos.system_repo import SystemRepository
from app.schemas.bot_speech import BotSpeechMessagePayload, BotSpeechUpdatePayload
from app.services.read_support import serialize_datetime


class BotSpeechService:
    def __init__(self, system_repo: SystemRepository) -> None:
        self.system_repo = system_repo

    def get_config(self, session: Session) -> dict[str, object]:
        now = self._now()
        messages = self.system_repo.list_active_bot_speech_messages(session, now=now)
        if messages:
            serialized = [self._serialize_message(entity, now=now) for entity in messages]
            first = serialized[0]
            return {
                "enabled": True,
                "message": first["message"],
                "updatedAt": first["updatedAt"],
                "messages": serialized,
                "pollIntervalSeconds": 15,
            }

        legacy = self.system_repo.get_bot_speech_config(session)
        if legacy is not None and legacy.enabled and legacy.message:
            legacy_message = {
                "id": 0,
                "message": legacy.message,
                "displayStyle": "STANDARD",
                "displayDurationSeconds": 0,
                "priority": 0,
                "status": "PUBLISHED",
                "startsAt": None,
                "endsAt": None,
                "updatedAt": serialize_datetime(legacy.updated_at),
            }
            return {
                "enabled": True,
                "message": legacy.message,
                "updatedAt": serialize_datetime(legacy.updated_at),
                "messages": [legacy_message],
                "pollIntervalSeconds": 15,
            }
        return {
            "enabled": False,
            "message": "",
            "updatedAt": None,
            "messages": [],
            "pollIntervalSeconds": 15,
        }

    def list_messages(self, session: Session) -> dict[str, object]:
        now = self._now()
        items = [
            self._serialize_message(entity, now=now, include_audit=True)
            for entity in self.system_repo.list_bot_speech_messages(session)
        ]
        return {"items": items, "total": len(items)}

    def create_message(
        self,
        session: Session,
        *,
        admin_user_id: int,
        payload: BotSpeechMessagePayload,
    ) -> dict[str, object]:
        starts_at, ends_at = self._validate_payload(payload)
        entity = BotSpeechMessageRecord(
            message=payload.message,
            display_style=payload.display_style,
            display_duration_seconds=payload.display_duration_seconds,
            priority=payload.priority,
            status="PUBLISHED" if payload.publish else "DRAFT",
            starts_at=starts_at,
            ends_at=ends_at,
            created_by_user_id=admin_user_id,
            updated_by_user_id=admin_user_id,
        )
        legacy = self.system_repo.get_bot_speech_config(session)
        if legacy is not None and legacy.enabled:
            legacy.enabled = False
            legacy.updated_by_user_id = admin_user_id
            self.system_repo.save_bot_speech_config(session, legacy)
        self.system_repo.save_bot_speech_message(session, entity)
        session.commit()
        return self._serialize_message(entity, now=self._now(), include_audit=True)

    def update_message(
        self,
        session: Session,
        *,
        message_id: int,
        admin_user_id: int,
        payload: BotSpeechMessagePayload,
    ) -> dict[str, object]:
        entity = self._require_message(session, message_id)
        if entity.status == "REVOKED":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="已撤回的台词不能再次编辑，请新建一条")
        starts_at, ends_at = self._validate_payload(payload)
        entity.message = payload.message
        entity.display_style = payload.display_style
        entity.display_duration_seconds = payload.display_duration_seconds
        entity.priority = payload.priority
        entity.status = "PUBLISHED" if payload.publish else "DRAFT"
        entity.starts_at = starts_at
        entity.ends_at = ends_at
        entity.updated_by_user_id = admin_user_id
        self.system_repo.save_bot_speech_message(session, entity)
        session.commit()
        return self._serialize_message(entity, now=self._now(), include_audit=True)

    def revoke_message(self, session: Session, *, message_id: int, admin_user_id: int) -> dict[str, object]:
        entity = self._require_message(session, message_id)
        if entity.status != "REVOKED":
            entity.status = "REVOKED"
            entity.revoked_at = self._now()
            entity.revoked_by_user_id = admin_user_id
            entity.updated_by_user_id = admin_user_id
            self.system_repo.save_bot_speech_message(session, entity)
            session.commit()
        return self._serialize_message(entity, now=self._now(), include_audit=True)

    def update_config(
        self,
        session: Session,
        *,
        admin_user_id: int,
        payload: BotSpeechUpdatePayload,
    ) -> dict[str, object]:
        """Keep the original singleton endpoint compatible with already-open admin pages."""
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
        return self.get_config(session)

    def _validate_payload(self, payload: BotSpeechMessagePayload) -> tuple[datetime | None, datetime | None]:
        starts_at = self._database_datetime(payload.starts_at)
        ends_at = self._database_datetime(payload.ends_at)
        if payload.publish and ends_at is not None and ends_at <= self._now():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="发布结束时间不能早于当前时间")
        return starts_at, ends_at

    def _require_message(self, session: Session, message_id: int) -> BotSpeechMessageRecord:
        entity = self.system_repo.get_bot_speech_message(session, message_id)
        if entity is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="宠物台词不存在")
        return entity

    def _serialize_message(
        self,
        entity: BotSpeechMessageRecord,
        *,
        now: datetime,
        include_audit: bool = False,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "id": entity.id,
            "message": entity.message,
            "displayStyle": entity.display_style,
            "displayDurationSeconds": entity.display_duration_seconds,
            "priority": entity.priority,
            "status": self._effective_status(entity, now),
            "startsAt": self._serialize_database_datetime(entity.starts_at),
            "endsAt": self._serialize_database_datetime(entity.ends_at),
            "updatedAt": serialize_datetime(entity.updated_at),
        }
        if include_audit:
            payload.update(
                {
                    "createdAt": serialize_datetime(entity.created_at),
                    "createdByUserId": entity.created_by_user_id,
                    "updatedByUserId": entity.updated_by_user_id,
                    "revokedAt": self._serialize_database_datetime(entity.revoked_at),
                    "revokedByUserId": entity.revoked_by_user_id,
                }
            )
        return payload

    def _effective_status(self, entity: BotSpeechMessageRecord, now: datetime) -> str:
        if entity.status in {"DRAFT", "REVOKED"}:
            return entity.status
        if entity.ends_at is not None and entity.ends_at <= now:
            return "EXPIRED"
        if entity.starts_at is not None and entity.starts_at > now:
            return "SCHEDULED"
        return "PUBLISHED"

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    @staticmethod
    def _database_datetime(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value
        return value.astimezone(UTC).replace(tzinfo=None)

    @staticmethod
    def _serialize_database_datetime(value: datetime | None) -> str | None:
        if value is None:
            return None
        normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return normalized.astimezone(UTC).isoformat().replace("+00:00", "Z")
