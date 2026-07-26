from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import Field, field_validator, model_validator
from sqlalchemy.orm import Session

from app.agentic_platform.domain import DomainModel
from app.core.config import Settings
from app.models.agentic_runtime import AgentOutboxRecord

from .outbox import AgentOutboxRepository


class ProactiveTriggerType(StrEnum):
    MATERIAL_DOWNLOADED = "material_downloaded"
    DAILY_BRIEF_DUE = "daily_brief_due"


class MaterialDownloadedTriggerPayload(DomainModel):
    schema_version: str = "1.0"
    material_id: int = Field(gt=0)
    material_title: str = Field(min_length=1, max_length=512)

    @field_validator("material_title")
    @classmethod
    def reject_blank_title(cls, value: str) -> str:
        normalized = " ".join(value.split()).strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized


class DailyBriefDueTriggerPayload(DomainModel):
    schema_version: str = "1.0"
    for_date: date


TriggerPayload = MaterialDownloadedTriggerPayload | DailyBriefDueTriggerPayload


class ProactiveTrigger(DomainModel):
    """Typed, bounded event input for the proactive policy boundary."""

    schema_version: str = "1.0"
    event_id: str = Field(min_length=1, max_length=64)
    event_type: ProactiveTriggerType
    admin_actor_id: int = Field(gt=0)
    aggregate_type: str = Field(min_length=1, max_length=64)
    aggregate_id: str = Field(min_length=1, max_length=128)
    payload: TriggerPayload

    @model_validator(mode="after")
    def require_matching_payload(self) -> "ProactiveTrigger":
        if self.event_type == ProactiveTriggerType.MATERIAL_DOWNLOADED and not isinstance(
            self.payload, MaterialDownloadedTriggerPayload
        ):
            raise ValueError("material_downloaded requires material payload")
        if self.event_type == ProactiveTriggerType.DAILY_BRIEF_DUE and not isinstance(
            self.payload, DailyBriefDueTriggerPayload
        ):
            raise ValueError("daily_brief_due requires daily brief payload")
        return self


def trigger_from_outbox(record: AgentOutboxRecord, repository: AgentOutboxRepository | None = None) -> ProactiveTrigger:
    payload = (repository or AgentOutboxRepository()).decode_payload(record)
    event_type = ProactiveTriggerType(record.event_type)
    if event_type == ProactiveTriggerType.MATERIAL_DOWNLOADED:
        typed_payload: TriggerPayload = MaterialDownloadedTriggerPayload.model_validate(payload)
    else:
        typed_payload = DailyBriefDueTriggerPayload.model_validate(payload)
    return ProactiveTrigger(
        event_id=record.id,
        event_type=event_type,
        admin_actor_id=record.admin_actor_id,
        aggregate_type=record.aggregate_type,
        aggregate_id=record.aggregate_id,
        payload=typed_payload,
    )


class ProactiveTriggerService:
    """Writes typed trigger facts into the transaction that observed them.

    The service does not notify learners and does not run a model.  It only
    records a durable Shadow Mode input that an independently started worker
    may process later.
    """

    def __init__(self, settings: Settings, *, outbox_repository: AgentOutboxRepository | None = None) -> None:
        self.settings = settings
        self.outbox = outbox_repository or AgentOutboxRepository()

    @property
    def shadow_admin_actor_id(self) -> int | None:
        value = self.settings.agentic_shadow_admin_actor_id
        return int(value) if value is not None and int(value) > 0 else None

    def is_enabled(self) -> bool:
        return bool(
            self.settings.agentic_platform_enabled
            and self.settings.agentic_proactive_enabled
            and self.shadow_admin_actor_id is not None
        )

    def enqueue_material_downloaded(
        self,
        session: Session,
        *,
        material_id: int,
        material_title: str,
        downloaded_by_user_id: int,
    ) -> tuple[AgentOutboxRecord, bool] | None:
        if not self.is_enabled():
            return None
        if material_id <= 0 or downloaded_by_user_id <= 0:
            raise ValueError("material_id and downloaded_by_user_id must be positive")
        payload = MaterialDownloadedTriggerPayload(material_id=material_id, material_title=material_title)
        return self.outbox.enqueue(
            session,
            event_type=ProactiveTriggerType.MATERIAL_DOWNLOADED.value,
            aggregate_type="material_download",
            aggregate_id=f"material:{material_id}:user:{downloaded_by_user_id}",
            admin_actor_id=self._require_shadow_admin_actor_id(),
            payload=payload.model_dump(mode="json"),
            idempotency_key=f"proactive:material-download:{material_id}:{downloaded_by_user_id}",
            max_attempts=self.settings.agentic_worker_max_attempts,
        )

    def enqueue_daily_brief_due(
        self,
        session: Session,
        *,
        for_date: date,
    ) -> tuple[AgentOutboxRecord, bool] | None:
        if not self.is_enabled():
            return None
        actor_id = self._require_shadow_admin_actor_id()
        payload = DailyBriefDueTriggerPayload(for_date=for_date)
        return self.outbox.enqueue(
            session,
            event_type=ProactiveTriggerType.DAILY_BRIEF_DUE.value,
            aggregate_type="daily_brief",
            aggregate_id=f"admin:{actor_id}:date:{for_date.isoformat()}",
            admin_actor_id=actor_id,
            payload=payload.model_dump(mode="json"),
            idempotency_key=f"proactive:daily-brief:{actor_id}:{for_date.isoformat()}",
            max_attempts=self.settings.agentic_worker_max_attempts,
        )

    def _require_shadow_admin_actor_id(self) -> int:
        actor_id = self.shadow_admin_actor_id
        if actor_id is None:
            raise RuntimeError("proactive Shadow Mode requires an administrator actor ID")
        return actor_id
