from __future__ import annotations

import re
from typing import Any

from app.models.materials import MaterialRecord
from app.services.material_pdf_evidence_service import MaterialPageEvidence


FORBIDDEN_INTERNAL_MARKERS = (
    "memory_context",
    "user_personal_memory",
    "platform_collective_memory",
    "conversation_context",
    "conversation_focus",
    "privacy_boundary",
    "candidate_materials",
    "image_attachments",
    "_image_attachment_data_urls",
    "pdf_evidence",
    "output_guardrail",
    "query_plan",
    "problem_context",
    "material_scope",
    "current_query_memory",
    "learning_preferences",
    "exam_analysis_focus",
    "course_memory_card",
    "evidence_coverage",
    "evidence_basis",
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

PROMPT_TEXT_FIELD_LIMITS = {
    "text": 700,
    "anchor_text": 240,
    "excerpt": 240,
    "description": 240,
    "summary": 240,
    "reason": 260,
    "title": 120,
    "answer": 1200,
    "conversation_focus": 650,
}

PROMPT_DEFAULT_TEXT_LIMIT = 500


class AgentSafetyService:
    """Post-process external Agent output before it reaches the API response."""

    def sanitize_prompt_payload(self, value: Any, *, field_name: str | None = None) -> Any:
        """Redact sensitive string values before sending context to a model."""

        if isinstance(value, dict):
            return {key: self.sanitize_prompt_payload(item, field_name=str(key)) for key, item in value.items()}
        if isinstance(value, list):
            return [self.sanitize_prompt_payload(item, field_name=field_name) for item in value]
        if isinstance(value, tuple):
            return [self.sanitize_prompt_payload(item, field_name=field_name) for item in value]
        if isinstance(value, str):
            return _clean_prompt_text(value, field_name=field_name)
        return value

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
        followup_questions = self._sanitize_followups(body.get("followup_questions"), candidate_materials=candidate_materials)

        if had_recommendation_list and not recommendations:
            answer = ""
        if answer and candidate_materials and _answer_denies_candidate_materials(answer):
            return None
        if answer and _answer_mentions_unscoped_material_title(answer, candidate_materials, pdf_evidence):
            return None
        if answer and not pdf_evidence and _answer_overclaims_pdf_evidence(answer):
            return None
        if answer and pdf_evidence and _answer_mentions_unread_pdf_page(answer, pdf_evidence):
            return None
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

    def sanitize_public_response_body(
        self,
        body: dict[str, Any],
        *,
        candidate_materials: list[MaterialRecord],
        pdf_evidence: list[MaterialPageEvidence],
    ) -> dict[str, Any]:
        """Clean locally generated Agent output while preserving public fields."""

        allowed_material_ids = {int(material.id) for material in candidate_materials}
        recommendations = self._sanitize_public_recommendations(body.get("recommendations"), allowed_material_ids)
        answer = self._sanitize_answer(body.get("answer"))
        evidence_sources = self._sanitize_public_evidence_sources(body.get("evidence_sources"), pdf_evidence)
        followup_questions = self._sanitize_followups(body.get("followup_questions"), candidate_materials=candidate_materials)

        if answer and pdf_evidence:
            if not evidence_sources:
                evidence_sources = self._fallback_evidence_sources(pdf_evidence)
            answer = self._ensure_answer_has_source_hint(answer, evidence_sources)
        elif answer:
            answer = self._ensure_low_evidence_caveat(answer)

        sanitized: dict[str, Any] = {}
        if recommendations:
            sanitized["recommendations"] = recommendations
        if answer:
            sanitized["answer"] = answer
        if followup_questions:
            sanitized["followup_questions"] = followup_questions
        if evidence_sources:
            sanitized["evidence_sources"] = evidence_sources
        return sanitized

    def _sanitize_recommendations(self, value: Any, allowed_material_ids: set[int]) -> tuple[list[dict[str, Any]], bool]:
        if not isinstance(value, list):
            return [], False
        items: list[dict[str, Any]] = []
        seen_material_ids: set[int] = set()
        for raw_item in value:
            if not isinstance(raw_item, dict):
                continue
            material_id = _safe_int(raw_item.get("material_id") or raw_item.get("materialId") or raw_item.get("id"))
            if material_id is None or material_id not in allowed_material_ids:
                continue
            if material_id in seen_material_ids:
                continue
            seen_material_ids.add(material_id)
            reason = _clean_public_text(raw_item.get("reason"), max_chars=180)
            item: dict[str, Any] = {"material_id": material_id}
            if reason:
                item["reason"] = reason
            items.append(item)
            if len(items) >= 3:
                break
        return items, True

    def _sanitize_public_recommendations(self, value: Any, allowed_material_ids: set[int]) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        items: list[dict[str, Any]] = []
        seen_material_ids: set[int] = set()
        for raw_item in value:
            if not isinstance(raw_item, dict):
                continue
            material_id = _safe_int(raw_item.get("material_id") or raw_item.get("materialId") or raw_item.get("id"))
            if material_id is None or material_id not in allowed_material_ids or material_id in seen_material_ids:
                continue
            seen_material_ids.add(material_id)
            item: dict[str, Any] = {"material_id": material_id}
            title = _clean_public_title(raw_item.get("title"), max_chars=120)
            if title:
                item["title"] = title
            tags = _clean_public_tags(raw_item.get("tags"))
            if tags:
                item["tags"] = tags
            reason = _clean_public_text(raw_item.get("reason"), max_chars=220)
            if reason:
                item["reason"] = reason
            summary = _clean_public_text(raw_item.get("summary"), max_chars=300)
            if summary:
                item["summary"] = summary
            items.append(item)
            if len(items) >= 3:
                break
        return items

    def _sanitize_answer(self, value: Any) -> str:
        if not isinstance(value, str):
            return ""
        answer = _clean_public_text(value, max_chars=1800)
        if not answer:
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
        seen_sources: set[tuple[int, int]] = set()
        for raw_item in value:
            if not isinstance(raw_item, dict):
                continue
            material_id = _safe_int(raw_item.get("material_id") or raw_item.get("materialId") or raw_item.get("id"))
            page = _safe_int(raw_item.get("page"))
            if material_id is None or page is None or (material_id, page) not in allowed:
                continue
            source_key = (material_id, page)
            if source_key in seen_sources:
                continue
            seen_sources.add(source_key)
            evidence = allowed[(material_id, page)]
            source: dict[str, Any] = {
                "material_id": material_id,
                "title": _clean_public_title(evidence.title, max_chars=120),
                "page": page,
            }
            excerpt = _clean_public_text(evidence.text, max_chars=240)
            if excerpt:
                source["excerpt"] = excerpt
            if evidence.years:
                source["years"] = list(evidence.years[:6])
            if evidence.question_types:
                source["question_types"] = list(evidence.question_types[:6])
            if evidence.question_numbers:
                source["question_numbers"] = list(evidence.question_numbers)
            if evidence.source_type != "unknown":
                source["source_type"] = evidence.source_type
            sources.append(source)
            if len(sources) >= 6:
                break
        return sources

    def _sanitize_public_evidence_sources(
        self,
        value: Any,
        pdf_evidence: list[MaterialPageEvidence],
    ) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        allowed = {(int(item.material_id), int(item.page)): item for item in pdf_evidence}
        sources: list[dict[str, Any]] = []
        seen_sources: set[tuple[int, int]] = set()
        for raw_item in value:
            if not isinstance(raw_item, dict):
                continue
            material_id = _safe_int(raw_item.get("material_id") or raw_item.get("materialId") or raw_item.get("id"))
            page = _safe_int(raw_item.get("page"))
            if material_id is None or page is None or (material_id, page) not in allowed:
                continue
            source_key = (material_id, page)
            if source_key in seen_sources:
                continue
            seen_sources.add(source_key)
            evidence = allowed[source_key]
            source: dict[str, Any] = {
                "material_id": material_id,
                "title": _clean_public_title(evidence.title, max_chars=120),
                "page": page,
            }
            excerpt = _clean_public_text(evidence.text, max_chars=240)
            if excerpt:
                source["excerpt"] = excerpt
            if evidence.years:
                source["years"] = list(evidence.years[:6])
            if evidence.question_types:
                source["question_types"] = list(evidence.question_types[:6])
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
                "title": _clean_public_title(evidence.title, max_chars=120),
                "page": int(evidence.page),
            }
            excerpt = _clean_public_text(evidence.text, max_chars=240)
            if excerpt:
                source["excerpt"] = excerpt
            if evidence.years:
                source["years"] = list(evidence.years[:6])
            if evidence.question_types:
                source["question_types"] = list(evidence.question_types[:6])
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

    def _sanitize_followups(self, value: Any, *, candidate_materials: list[MaterialRecord] | None = None) -> list[str]:
        if not isinstance(value, list):
            return []
        questions: list[str] = []
        seen_questions: set[str] = set()
        has_candidate_materials = bool(candidate_materials)
        for item in value:
            question = _clean_public_text(item, max_chars=80)
            if not question:
                continue
            lowered = question.lower()
            if any(marker in lowered for marker in FORBIDDEN_INTERNAL_MARKERS):
                continue
            if has_candidate_materials and _followup_requests_external_material(question):
                continue
            if lowered in seen_questions:
                continue
            seen_questions.add(lowered)
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
    text = _redact_public_sensitive_text(_clean_text(value, max_chars=max_chars))[:max_chars]
    if not text:
        return ""
    lowered = text.lower()
    if any(marker in lowered for marker in FORBIDDEN_INTERNAL_MARKERS):
        return ""
    return text


def _clean_public_title(value: Any, *, max_chars: int) -> str:
    text = _redact_public_sensitive_text(_clean_text(value, max_chars=max_chars))[:max_chars]
    if not text:
        return "资料"
    lowered = text.lower()
    if any(marker in lowered for marker in FORBIDDEN_INTERNAL_MARKERS):
        return "资料"
    return text


def _clean_prompt_text(value: str, *, field_name: str | None) -> str:
    limit = PROMPT_TEXT_FIELD_LIMITS.get(str(field_name or "").lower(), PROMPT_DEFAULT_TEXT_LIMIT)
    return _redact_public_sensitive_text(_clean_text(value, max_chars=max(limit * 2, limit)))[:limit]


def _clean_public_tags(value: Any) -> list[str]:
    return _clean_public_list(value, limit=8, max_chars=40)


def _clean_public_list(value: Any, *, limit: int, max_chars: int) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        cleaned = _clean_public_text(item, max_chars=max_chars)
        if cleaned and cleaned not in result:
            result.append(cleaned)
        if len(result) >= limit:
            break
    return result


def _redact_public_sensitive_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(
        r"https?://[^\s,;，；。]+|www\.[^\s,;，；。]+",
        "[redacted-url]",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[redacted-email]", text)
    text = re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "[redacted-phone]", text)
    text = re.sub(
        r"(?i)(api[_-]?key|token|secret|authorization|bearer)\s*[:=]\s*[^\s,;，；。]+",
        "[redacted-secret]",
        text,
    )
    text = re.sub(
        r"(?i)(?<![A-Za-z0-9_-])(?:sk|tp)-[A-Za-z0-9_-]{16,}(?![A-Za-z0-9_-])",
        "[redacted-secret]",
        text,
    )
    text = _redact_identity_numbers(text)
    text = _redact_labeled_ids(text)
    text = _redact_messenger_handles(text)
    return re.sub(r"(?<!\d)\d{12,24}(?!\d)", "[redacted-number]", text)


def _redact_identity_numbers(text: str) -> str:
    return re.sub(
        r"(?<![A-Za-z0-9])\d{6}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?![A-Za-z0-9])",
        "[redacted-id-card]",
        text,
    )


def _redact_labeled_ids(text: str) -> str:
    pattern = re.compile(
        r"(?i)(学号|工号|student[_ -]?id|employee[_ -]?id)\s*[:：=]?\s*[A-Za-z0-9_-]{5,24}"
    )
    return pattern.sub(lambda match: f"{match.group(1)}=[redacted-id]", text)


def _redact_messenger_handles(text: str) -> str:
    latin_pattern = re.compile(
        r"(?i)(?<![A-Za-z0-9_])(qq|wechat|weixin|wx|vx)(?![A-Za-z0-9_])\s*[:：=]?\s*[A-Za-z0-9_-]{5,32}"
    )
    text = latin_pattern.sub(lambda match: f"{match.group(1)}=[redacted-contact]", text)
    chinese_pattern = re.compile(r"(微信|微信号|微 信)\s*[:：=]?\s*[A-Za-z0-9_-]{5,32}")
    return chinese_pattern.sub(lambda match: f"{match.group(1)}=[redacted-contact]", text)


def _answer_mentions_source(answer: str, evidence_sources: list[dict[str, Any]]) -> bool:
    normalized = answer.lower()
    for source in evidence_sources:
        title = _clean_public_title(source.get("title"), max_chars=120)
        page = _safe_int(source.get("page"))
        title_mentioned = bool(title and title.lower() in normalized)
        page_mentioned = page is not None and (f"第 {page} 页" in answer or f"第{page}页" in answer)
        if title_mentioned and page_mentioned:
            return True
        if page_mentioned and len(evidence_sources) == 1:
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


def _answer_denies_candidate_materials(answer: str) -> bool:
    normalized = re.sub(r"\s+", "", answer).lower()
    markers = (
        "没有收到任何",
        "没有收到可用",
        "没有可用的studyhub候选资料",
        "没有可用studyhub候选资料",
        "没有候选资料",
        "没有studyhub候选资料",
        "不能基于指定资料",
        "无法基于指定资料",
        "没有匹配到相关资料",
    )
    return any(marker in normalized for marker in markers)


def _answer_mentions_unscoped_material_title(
    answer: str,
    candidate_materials: list[MaterialRecord],
    pdf_evidence: list[MaterialPageEvidence],
) -> bool:
    quoted_titles = [
        _clean_public_title(title, max_chars=160)
        for title in re.findall(r"《([^》]{2,160})》", answer)
    ]
    material_like_titles = [title for title in quoted_titles if _looks_like_material_title(title)]
    if not material_like_titles:
        return False

    allowed_titles = [
        _clean_public_title(getattr(material, "title", ""), max_chars=160)
        for material in candidate_materials
    ]
    allowed_titles.extend(_clean_public_title(item.title, max_chars=160) for item in pdf_evidence)
    allowed_titles = [title for title in allowed_titles if title and title != "资料"]
    return any(not _title_matches_allowed_scope(title, allowed_titles) for title in material_like_titles)


def _followup_requests_external_material(question: str) -> bool:
    normalized = re.sub(r"\s+", "", question).lower()
    request_markers = (
        "发给我",
        "发我",
        "发一下",
        "上传",
        "传一下",
        "提供",
        "给我",
        "贴一下",
    )
    material_markers = (
        "资料",
        "真题",
        "往年题",
        "历年题",
        "试卷",
        "样卷",
        "讲义",
        "笔记",
        "pdf",
        "文件",
    )
    return any(marker in normalized for marker in request_markers) and any(
        marker in normalized for marker in material_markers
    )


def _looks_like_material_title(title: str) -> bool:
    normalized = re.sub(r"\s+", "", title).lower()
    markers = (
        "资料",
        "pdf",
        "真题",
        "往年",
        "历年",
        "试卷",
        "样卷",
        "期末",
        "期中",
        "答案",
        "解析",
        "笔记",
        "讲义",
        "速成",
        "复习",
    )
    return any(marker in normalized for marker in markers) or bool(re.search(r"20[0-3]\d", normalized))


def _title_matches_allowed_scope(title: str, allowed_titles: list[str]) -> bool:
    normalized_title = _normalize_title_for_scope(title)
    if not normalized_title:
        return False
    for allowed_title in allowed_titles:
        normalized_allowed = _normalize_title_for_scope(allowed_title)
        if not normalized_allowed:
            continue
        if normalized_title == normalized_allowed:
            return True
        if min(len(normalized_title), len(normalized_allowed)) >= 6 and (
            normalized_title in normalized_allowed or normalized_allowed in normalized_title
        ):
            return True
    return False


def _normalize_title_for_scope(title: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", title).lower()


def _answer_overclaims_pdf_evidence(answer: str) -> bool:
    normalized = re.sub(r"\s+", "", answer).lower()
    markers = (
        "已读取pdf",
        "读取到相关pdf",
        "读到相关pdf",
        "看了pdf",
        "pdf页级证据",
        "已读取页码",
        "已读页面",
        "引用页",
    )
    if any(marker in normalized for marker in markers):
        return True
    if re.search(r"第\d{1,4}页", normalized):
        return True
    if re.search(r"来源[:：]?《[^》]{1,120}》第\d{1,4}页", normalized):
        return True
    return False


def _answer_mentions_unread_pdf_page(answer: str, pdf_evidence: list[MaterialPageEvidence]) -> bool:
    allowed_pages = {int(item.page) for item in pdf_evidence}
    if not allowed_pages:
        return False
    mentioned_pages = _answer_pdf_page_numbers(answer)
    return any(page not in allowed_pages for page in mentioned_pages)


def _answer_pdf_page_numbers(answer: str) -> list[int]:
    pages: list[int] = []
    for raw_page in re.findall(r"第\s*(\d{1,4})\s*页", answer):
        page = _safe_int(raw_page)
        if page is not None and page not in pages:
            pages.append(page)
    return pages


def _source_hint(evidence_sources: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for source in evidence_sources[:3]:
        title = _clean_public_title(source.get("title"), max_chars=80)
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
