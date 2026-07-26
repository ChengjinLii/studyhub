from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator

from app.agentic_platform.domain import DomainModel

from .triggers import (
    DailyBriefDueTriggerPayload,
    MaterialDownloadedTriggerPayload,
    ProactiveTrigger,
    ProactiveTriggerType,
)


class ShadowInterventionType(StrEnum):
    MATERIAL_ANALYSIS = "material_analysis"
    DAILY_BRIEF = "daily_brief"


class MaterialAnalysisJobPayload(DomainModel):
    schema_version: str = "1.0"
    intervention_type: Literal[ShadowInterventionType.MATERIAL_ANALYSIS] = ShadowInterventionType.MATERIAL_ANALYSIS
    outbox_event_id: str = Field(min_length=1, max_length=64)
    material_id: int = Field(gt=0)
    material_title: str = Field(min_length=1, max_length=512)
    shadow_mode: Literal[True] = True

    @field_validator("material_title")
    @classmethod
    def reject_blank_title(cls, value: str) -> str:
        normalized = " ".join(value.split()).strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized


class DailyBriefJobPayload(DomainModel):
    schema_version: str = "1.0"
    intervention_type: Literal[ShadowInterventionType.DAILY_BRIEF] = ShadowInterventionType.DAILY_BRIEF
    outbox_event_id: str = Field(min_length=1, max_length=64)
    for_date: str = Field(min_length=10, max_length=10)
    shadow_mode: Literal[True] = True


ProactiveJobPayload = MaterialAnalysisJobPayload | DailyBriefJobPayload


class ShadowIntervention(DomainModel):
    """A trigger-to-job mapping, not a scripted general-agent trajectory."""

    schema_version: str = "1.0"
    intervention_type: ShadowInterventionType
    job_type: str = Field(min_length=1, max_length=128)
    run_kind: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=512)
    goal: str = Field(min_length=1, max_length=2_000)
    success_criteria: list[str] = Field(min_length=1, max_length=12)
    payload: ProactiveJobPayload


class ShadowInterventionPolicy:
    """Conservative Shadow Mode routing for the two PR10 trigger contracts.

    It only selects the artifact category that a trigger is allowed to propose.
    The durable job still owns execution and may later bind to a richer policy
    or agent runtime without changing the outbox protocol.
    """

    version = "shadow-intervention-policy-v1"

    def decide(self, trigger: ProactiveTrigger) -> ShadowIntervention:
        if trigger.event_type == ProactiveTriggerType.MATERIAL_DOWNLOADED:
            payload = trigger.payload
            if not isinstance(payload, MaterialDownloadedTriggerPayload):
                raise ValueError("material_downloaded trigger payload is invalid")
            return ShadowIntervention(
                intervention_type=ShadowInterventionType.MATERIAL_ANALYSIS,
                job_type="proactive.material_analysis",
                run_kind="material_analysis",
                title=f"Shadow material analysis · {payload.material_title}",
                goal="Prepare a reviewable, evidence-grounded material analysis for administrators.",
                success_criteria=["Use authorized internal PDF page evidence", "Persist an admin-preview artifact only"],
                payload=MaterialAnalysisJobPayload(
                    outbox_event_id=trigger.event_id,
                    material_id=payload.material_id,
                    material_title=payload.material_title,
                ),
            )
        if trigger.event_type == ProactiveTriggerType.DAILY_BRIEF_DUE:
            payload = trigger.payload
            if not isinstance(payload, DailyBriefDueTriggerPayload):
                raise ValueError("daily_brief_due trigger payload is invalid")
            return ShadowIntervention(
                intervention_type=ShadowInterventionType.DAILY_BRIEF,
                job_type="proactive.daily_brief",
                run_kind="daily_brief",
                title=f"Shadow daily brief · {payload.for_date.isoformat()}",
                goal="Prepare an administrator-only daily brief from accepted learning artifacts.",
                success_criteria=["Reference accepted artifacts", "Remain administrator-preview only"],
                payload=DailyBriefJobPayload(
                    outbox_event_id=trigger.event_id,
                    for_date=payload.for_date.isoformat(),
                ),
            )
        raise ValueError(f"unsupported proactive trigger type: {trigger.event_type.value}")


def parse_proactive_job_payload(value: object) -> ProactiveJobPayload:
    if not isinstance(value, dict):
        raise ValueError("proactive job envelope must be an object")
    payload = value.get("proactive")
    if not isinstance(payload, dict):
        raise ValueError("proactive job payload is missing")
    intervention_type = payload.get("intervention_type")
    if intervention_type == ShadowInterventionType.MATERIAL_ANALYSIS.value:
        return MaterialAnalysisJobPayload.model_validate(payload)
    if intervention_type == ShadowInterventionType.DAILY_BRIEF.value:
        return DailyBriefJobPayload.model_validate(payload)
    raise ValueError("unsupported proactive job payload")
