from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Mapping

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.repos.material_repo import MaterialRepository
    from app.repos.read_api_repo import ReadApiRepository
    from app.agentic_platform.deepresearch.domain_router import ResearchCapabilityFlags, ResearchEnvironment
    from app.services.material_pdf_evidence_service import MaterialPdfEvidenceService
    from app.services.materials_service import MaterialsService


class SkillExecutionMode(StrEnum):
    LIVE = "live"
    FIXTURE = "fixture"
    SNAPSHOT = "snapshot"


@dataclass(slots=True)
class SkillExecutionContext:
    """Per-call authority and dependencies; it never exposes a whole agent thread."""

    admin_actor_id: int
    role_mask: int
    permission_scopes: frozenset[str]
    idempotency_key: str | None = None
    approval_granted: bool = False
    current_user_id: int | None = None
    current_user_role_mask: int | None = None
    session: Session | None = None
    material_repo: MaterialRepository | None = None
    read_repo: ReadApiRepository | None = None
    materials_service: MaterialsService | None = None
    pdf_evidence_service: MaterialPdfEvidenceService | None = None
    research_environment: ResearchEnvironment | None = None
    research_capability_flags: ResearchCapabilityFlags | None = None
    mode: SkillExecutionMode = SkillExecutionMode.LIVE
    fixture_outputs: Mapping[str, object] = field(default_factory=dict)

    def require_live_session(self) -> Session:
        if self.session is None:
            raise RuntimeError("live skill execution requires a database session")
        return self.session

    def require_material_repo(self) -> MaterialRepository:
        if self.material_repo is None:
            raise RuntimeError("material skill execution requires MaterialRepository")
        return self.material_repo

    def require_pdf_evidence_service(self) -> MaterialPdfEvidenceService:
        if self.pdf_evidence_service is None:
            raise RuntimeError("PDF evidence skill execution requires MaterialPdfEvidenceService")
        return self.pdf_evidence_service

    def require_materials_service(self) -> MaterialsService:
        if self.materials_service is None:
            raise RuntimeError("research skill execution requires MaterialsService")
        return self.materials_service

    def require_research_environment(self) -> ResearchEnvironment:
        if self.research_environment is None:
            raise RuntimeError("research skill execution requires a ResearchEnvironment")
        return self.research_environment
