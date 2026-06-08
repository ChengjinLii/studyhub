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
    "problem_context",
    "material_scope",
    "current_query_memory",
    "learning_preferences",
    "course_memory_card",
    "evidence_coverage",
    "confidence_assessment",
    "yearly_question_type_matrix",
    "chapter_distribution",
    "chapter_signals",
    "solution_signal_distribution",
    "solution_signals",
    "user_fit_signals",
    "material_quality_distribution",
    "material_risk_distribution",
    "anchor_text",
    "anchor_terms",
    "study_strategy_signals",
    "study_strategy_distribution",
    "experience_materials",
    "experience_material_ids",
    "strategy_refs",
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
        if answer and pdf_evidence:
            if not evidence_sources:
                evidence_sources = self._fallback_evidence_sources(pdf_evidence)
            answer = self._ensure_answer_has_source_hint(answer, evidence_sources)
        elif answer:
            answer = self._ensure_low_evidence_caveat(answer)
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
            reason = _clean_public_text(raw_item.get("reason"), max_chars=180)
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
            source: dict[str, Any] = {"material_id": material_id, "title": evidence.title, "page": page}
            if evidence.question_numbers:
                source["question_numbers"] = list(evidence.question_numbers)
            if evidence.source_type != "unknown":
                source["source_type"] = evidence.source_type
            sources.append(source)
            if len(sources) >= 6:
                break
        return sources

    def _fallback_evidence_sources(self, pdf_evidence: list[MaterialPageEvidence]) -> list[dict[str, Any]]:
        sources: list[dict[str, Any]] = []
        for evidence in pdf_evidence[:6]:
            source: dict[str, Any] = {
                "material_id": int(evidence.material_id),
                "title": evidence.title,
                "page": int(evidence.page),
            }
            if evidence.question_numbers:
                source["question_numbers"] = list(evidence.question_numbers)
            if evidence.source_type != "unknown":
                source["source_type"] = evidence.source_type
            sources.append(source)
        return sources

    def _ensure_answer_has_source_hint(self, answer: str, evidence_sources: list[dict[str, Any]]) -> str:
        if not answer or not evidence_sources or _answer_mentions_source(answer, evidence_sources):
            return answer
        hint = _source_hint(evidence_sources)
        if not hint:
            return answer
        max_chars = 1800
        trimmed_answer = answer[: max(0, max_chars - len(hint) - 1)].rstrip()
        return f"{trimmed_answer} {hint}".strip()

    def _ensure_low_evidence_caveat(self, answer: str) -> str:
        if not answer or _answer_mentions_low_evidence_boundary(answer):
            return answer
        caveat = "说明：当前没有可用 PDF 页级证据，这里仅基于候选资料元数据和可见记忆信号给出保守建议。"
        max_chars = 1800
        trimmed_answer = answer[: max(0, max_chars - len(caveat) - 1)].rstrip()
        return f"{trimmed_answer} {caveat}".strip()

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


def _clean_public_text(value: Any, *, max_chars: int) -> str:
    text = _clean_text(value, max_chars=max_chars)
    if not text:
        return ""
    lowered = text.lower()
    if any(marker in lowered for marker in FORBIDDEN_INTERNAL_MARKERS):
        return ""
    return text


def _answer_mentions_source(answer: str, evidence_sources: list[dict[str, Any]]) -> bool:
    normalized = answer.lower()
    for source in evidence_sources:
        title = _clean_text(source.get("title"), max_chars=120)
        page = _safe_int(source.get("page"))
        if title and title.lower() in normalized:
            return True
        if page is not None and (f"第 {page} 页" in answer or f"第{page}页" in answer):
            return True
    return False


def _answer_mentions_low_evidence_boundary(answer: str) -> bool:
    markers = (
        "没有可用 pdf",
        "缺少 pdf",
        "未读取 pdf",
        "候选资料元数据",
        "基于候选资料",
        "基于 studyhub 资料库",
        "保守建议",
    )
    normalized = answer.lower()
    return any(marker in normalized for marker in markers)


def _source_hint(evidence_sources: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for source in evidence_sources[:3]:
        title = _clean_text(source.get("title"), max_chars=80)
        page = _safe_int(source.get("page"))
        if not title or page is None:
            continue
        question_numbers = source.get("question_numbers")
        question_hint = ""
        if isinstance(question_numbers, list):
            cleaned = [_clean_text(item, max_chars=24) for item in question_numbers[:3]]
            cleaned = [item for item in cleaned if item]
            if cleaned:
                question_hint = f"（{', '.join(cleaned)}）"
        parts.append(f"《{title}》第 {page} 页{question_hint}")
    if not parts:
        return ""
    return f"来源：{'；'.join(parts)}。"
