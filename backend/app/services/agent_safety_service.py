from __future__ import annotations

import re
from typing import Any

from app.models.materials import MaterialRecord
from app.services.material_pdf_evidence_service import MaterialPageEvidence


FORBIDDEN_INTERNAL_MARKERS = (
    "memory_context",
    "user_personal_memory",
    "platform_collective_memory",
    "privacy_boundary",
    "candidate_materials",
    "pdf_evidence",
    "query_plan",
)


class AgentSafetyService:
    """Post-process external Agent output before it reaches the API response."""

    def sanitize_recommendation_body(
        self,
        body: dict[str, Any],
        *,
        candidate_materials: list[MaterialRecord],
        pdf_evidence: list[MaterialPageEvidence],
    ) -> dict[str, Any] | None:
        allowed_material_ids = {int(material.id) for material in candidate_materials}
        recommendations, had_recommendation_list = self._sanitize_recommendations(body.get("recommendations"), allowed_material_ids)
        answer = self._sanitize_answer(body.get("answer"))
        evidence_sources = self._sanitize_evidence_sources(body.get("evidence_sources"), pdf_evidence)
        followup_questions = self._sanitize_followups(body.get("followup_questions"))

        if had_recommendation_list and not recommendations:
            answer = ""
        if not answer and not recommendations:
            return None

        sanitized: dict[str, Any] = {}
        if answer:
            sanitized["answer"] = answer
        if recommendations:
            sanitized["recommendations"] = recommendations
        if evidence_sources:
            sanitized["evidence_sources"] = evidence_sources
        if followup_questions:
            sanitized["followup_questions"] = followup_questions
        return sanitized or None

    def _sanitize_recommendations(self, value: Any, allowed_material_ids: set[int]) -> tuple[list[dict[str, Any]], bool]:
        if not isinstance(value, list):
            return [], False
        items: list[dict[str, Any]] = []
        for raw_item in value:
            if not isinstance(raw_item, dict):
                continue
            material_id = _safe_int(raw_item.get("material_id") or raw_item.get("materialId") or raw_item.get("id"))
            if material_id is None or material_id not in allowed_material_ids:
                continue
            reason = _clean_text(raw_item.get("reason"), max_chars=180)
            item: dict[str, Any] = {"material_id": material_id}
            if reason:
                item["reason"] = reason
            items.append(item)
            if len(items) >= 3:
                break
        return items, True

    def _sanitize_answer(self, value: Any) -> str:
        if not isinstance(value, str):
            return ""
        answer = _clean_text(value, max_chars=1800)
        if not answer:
            return ""
        lowered = answer.lower()
        if any(marker in lowered for marker in FORBIDDEN_INTERNAL_MARKERS):
            return ""
        return answer

    def _sanitize_evidence_sources(
        self,
        value: Any,
        pdf_evidence: list[MaterialPageEvidence],
    ) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        allowed = {(int(item.material_id), int(item.page)): item for item in pdf_evidence}
        sources: list[dict[str, Any]] = []
        for raw_item in value:
            if not isinstance(raw_item, dict):
                continue
            material_id = _safe_int(raw_item.get("material_id") or raw_item.get("materialId") or raw_item.get("id"))
            page = _safe_int(raw_item.get("page"))
            if material_id is None or page is None or (material_id, page) not in allowed:
                continue
            evidence = allowed[(material_id, page)]
            sources.append({"material_id": material_id, "title": evidence.title, "page": page})
            if len(sources) >= 6:
                break
        return sources

    def _sanitize_followups(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        questions: list[str] = []
        for item in value:
            question = _clean_text(item, max_chars=80)
            if not question:
                continue
            lowered = question.lower()
            if any(marker in lowered for marker in FORBIDDEN_INTERNAL_MARKERS):
                continue
            questions.append(question)
            if len(questions) >= 3:
                break
        return questions


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clean_text(value: Any, *, max_chars: int) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()[:max_chars]
