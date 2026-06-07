from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from typing import Any

from app.models.materials import MaterialRecord
from app.services.agent_memory_service import AgentMemoryContext
from app.services.agent_query_planner_service import AgentQueryPlan
from app.services.material_pdf_evidence_service import MaterialPageEvidence


@dataclass(slots=True)
class CourseMemoryCard:
    course: str
    version: str
    version_fingerprint: str
    version_basis: dict[str, Any]
    source: str
    years: tuple[str, ...]
    question_type_distribution: tuple[dict[str, Any], ...]
    knowledge_signals: tuple[dict[str, Any], ...]
    score_point_distribution: tuple[dict[str, Any], ...]
    difficulty_distribution: tuple[dict[str, Any], ...]
    source_type_distribution: tuple[dict[str, Any], ...]
    high_signal_materials: tuple[dict[str, Any], ...]
    page_references: tuple[dict[str, Any], ...]
    recommended_sequence: tuple[str, ...]
    limitations: tuple[str, ...]

    def to_prompt_payload(self) -> dict[str, Any]:
        return {
            "course": self.course,
            "version": self.version,
            "version_fingerprint": self.version_fingerprint,
            "version_basis": self.version_basis,
            "source": self.source,
            "years": list(self.years),
            "question_type_distribution": list(self.question_type_distribution),
            "knowledge_signals": list(self.knowledge_signals),
            "score_point_distribution": list(self.score_point_distribution),
            "difficulty_distribution": list(self.difficulty_distribution),
            "source_type_distribution": list(self.source_type_distribution),
            "high_signal_materials": list(self.high_signal_materials),
            "page_references": list(self.page_references),
            "recommended_sequence": list(self.recommended_sequence),
            "limitations": list(self.limitations),
        }


class AgentCourseMemoryService:
    """Builds a compact per-request course collective memory card.

    This is not persisted yet. It is a bounded, read-only summary derived from
    already collected candidates, PDF evidence, query plan, and memory context.
    """

    def build_card(
        self,
        *,
        materials: list[MaterialRecord],
        pdf_evidence: list[MaterialPageEvidence],
        memory_context: AgentMemoryContext | None,
        query_plan: AgentQueryPlan | None,
    ) -> CourseMemoryCard | None:
        if not materials and not pdf_evidence:
            return None
        course = _resolve_course(materials, memory_context, query_plan)
        if not course:
            return None
        years = _resolve_years(pdf_evidence, memory_context, query_plan)
        question_types = _counter_payload(_question_type_counter(pdf_evidence, memory_context), limit=6)
        knowledge_signals = _counter_payload(_knowledge_counter(pdf_evidence), limit=8)
        score_points = _counter_payload(_score_point_counter(pdf_evidence), limit=8)
        difficulty_signals = _counter_payload(_difficulty_counter(pdf_evidence), limit=5)
        source_types = _counter_payload(_source_type_counter(pdf_evidence, memory_context), limit=5)
        version_basis = _version_basis(
            course=course,
            materials=materials,
            pdf_evidence=pdf_evidence,
            memory_context=memory_context,
            query_plan=query_plan,
        )
        fingerprint = _version_fingerprint(version_basis)
        return CourseMemoryCard(
            course=course,
            version=f"ephemeral-v1-{fingerprint[:12]}",
            version_fingerprint=fingerprint,
            version_basis=version_basis,
            source="current_request_candidates",
            years=tuple(years),
            question_type_distribution=tuple(question_types),
            knowledge_signals=tuple(knowledge_signals),
            score_point_distribution=tuple(score_points),
            difficulty_distribution=tuple(difficulty_signals),
            source_type_distribution=tuple(source_types),
            high_signal_materials=tuple(_high_signal_materials(materials)),
            page_references=tuple(_page_references(pdf_evidence)),
            recommended_sequence=tuple(_recommended_sequence(query_plan, bool(pdf_evidence))),
            limitations=tuple(_limitations(materials, pdf_evidence)),
        )


def _resolve_course(
    materials: list[MaterialRecord],
    memory_context: AgentMemoryContext | None,
    query_plan: AgentQueryPlan | None,
) -> str:
    if query_plan and query_plan.course_terms:
        return query_plan.course_terms[0]
    platform = memory_context.platform if memory_context else {}
    for item in platform.get("course_signals") or []:
        if isinstance(item, dict) and item.get("value"):
            return str(item["value"])
    for material in materials:
        for value in (material.major, material.college, material.course_category, material.title):
            cleaned = _clean_text(value)
            if cleaned:
                return cleaned
    return ""


def _resolve_years(
    pdf_evidence: list[MaterialPageEvidence],
    memory_context: AgentMemoryContext | None,
    query_plan: AgentQueryPlan | None,
) -> list[str]:
    years: list[str] = []
    if query_plan:
        years.extend(query_plan.years)
    for evidence in pdf_evidence:
        years.extend(evidence.years)
    platform = memory_context.platform if memory_context else {}
    for item in platform.get("pdf_year_signals") or []:
        if isinstance(item, dict) and item.get("value"):
            years.append(str(item["value"]))
    return _dedupe([year for year in years if year])[:8]


def _question_type_counter(
    pdf_evidence: list[MaterialPageEvidence],
    memory_context: AgentMemoryContext | None,
) -> Counter[str]:
    counter: Counter[str] = Counter()
    for evidence in pdf_evidence:
        counter.update(evidence.question_types)
    if pdf_evidence:
        return counter
    platform = memory_context.platform if memory_context else {}
    for item in platform.get("pdf_question_type_signals") or []:
        if isinstance(item, dict) and item.get("value"):
            counter[str(item["value"])] += int(item.get("count") or 1)
    return counter


def _knowledge_counter(pdf_evidence: list[MaterialPageEvidence]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for evidence in pdf_evidence:
        counter.update(evidence.knowledge_signals)
    return counter


def _score_point_counter(pdf_evidence: list[MaterialPageEvidence]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for evidence in pdf_evidence:
        counter.update(str(value) for value in evidence.score_points)
    return counter


def _difficulty_counter(pdf_evidence: list[MaterialPageEvidence]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for evidence in pdf_evidence:
        counter.update(evidence.difficulty_signals)
    return counter


def _source_type_counter(
    pdf_evidence: list[MaterialPageEvidence],
    memory_context: AgentMemoryContext | None,
) -> Counter[str]:
    counter: Counter[str] = Counter()
    for evidence in pdf_evidence:
        if evidence.source_type != "unknown":
            counter[evidence.source_type] += 1
    if pdf_evidence:
        return counter
    platform = memory_context.platform if memory_context else {}
    for item in platform.get("pdf_source_type_signals") or []:
        if isinstance(item, dict) and item.get("value"):
            counter[str(item["value"])] += int(item.get("count") or 1)
    return counter


def _high_signal_materials(materials: list[MaterialRecord]) -> list[dict[str, Any]]:
    result = []
    for material in sorted(
        materials,
        key=lambda item: (
            -int(item.download_count or 0),
            -float(item.rating_avg or 0),
            -int(item.like_count or 0),
            int(item.id),
        ),
    )[:4]:
        result.append(
            {
                "material_id": int(material.id),
                "title": _clean_text(material.title),
                "downloads": int(material.download_count or 0),
                "rating_avg": float(material.rating_avg or 0),
            }
        )
    return result


def _page_references(pdf_evidence: list[MaterialPageEvidence]) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    for evidence in pdf_evidence[:8]:
        payload: dict[str, Any] = {
            "material_id": evidence.material_id,
            "title": evidence.title,
            "page": evidence.page,
        }
        if evidence.years:
            payload["years"] = list(evidence.years)
        if evidence.question_types:
            payload["question_types"] = list(evidence.question_types)
        if evidence.question_numbers:
            payload["question_numbers"] = list(evidence.question_numbers)
        if evidence.score_points:
            payload["score_points"] = list(evidence.score_points)
        if evidence.difficulty_signals:
            payload["difficulty_signals"] = list(evidence.difficulty_signals)
        if evidence.source_type != "unknown":
            payload["source_type"] = evidence.source_type
        references.append(payload)
    return references


def _recommended_sequence(query_plan: AgentQueryPlan | None, has_pdf_evidence: bool) -> list[str]:
    if query_plan and query_plan.intent == "exam_trend_analysis":
        return ["先看高频题型", "再核对年份趋势", "最后按页码打开真题资料查漏补缺"]
    if query_plan and query_plan.intent == "study_plan":
        return ["先建立知识框架", "再刷真题或例题", "最后复盘错题和薄弱点"]
    if has_pdf_evidence:
        return ["先读已引用页码", "再看推荐资料全文", "最后根据追问细化题型"]
    return ["先确认课程范围", "再筛选最相关资料", "最后补充题型或年份要求"]


def _limitations(materials: list[MaterialRecord], pdf_evidence: list[MaterialPageEvidence]) -> list[str]:
    limitations = []
    if not pdf_evidence:
        limitations.append("当前请求没有可用 PDF 页级证据，课程记忆卡片只基于候选资料元数据生成。")
    if len(materials) <= 1:
        limitations.append("候选资料较少，跨年份趋势判断需要更多资料支撑。")
    if not limitations:
        limitations.append("该卡片为当前请求的只读临时汇总，尚未持久化为平台正式课程记忆。")
    return limitations


def _version_basis(
    *,
    course: str,
    materials: list[MaterialRecord],
    pdf_evidence: list[MaterialPageEvidence],
    memory_context: AgentMemoryContext | None,
    query_plan: AgentQueryPlan | None,
) -> dict[str, Any]:
    platform = memory_context.platform if memory_context else {}
    return {
        "schema": "course-memory-card-v1",
        "course": course,
        "material_ids": sorted({int(material.id) for material in materials})[:12],
        "evidence_refs": [
            _evidence_ref_basis(item)
            for item in sorted(pdf_evidence[:12], key=lambda evidence: (int(evidence.material_id), int(evidence.page)))
        ],
        "query_plan": _query_plan_basis(query_plan),
        "platform_signal_keys": sorted(str(key) for key, value in platform.items() if value not in (None, [], {}, "")),
    }


def _evidence_ref_basis(item: MaterialPageEvidence) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "material_id": int(item.material_id),
        "page": int(item.page),
        "years": list(item.years),
        "question_types": list(item.question_types),
        "question_numbers": list(item.question_numbers),
        "source_type": item.source_type,
    }
    if item.score_points:
        payload["score_points"] = list(item.score_points)
    if item.difficulty_signals:
        payload["difficulty_signals"] = list(item.difficulty_signals)
    return payload


def _query_plan_basis(query_plan: AgentQueryPlan | None) -> dict[str, Any]:
    if query_plan is None:
        return {}
    return {
        "intent": query_plan.intent,
        "course_terms": list(query_plan.course_terms),
        "resource_types": list(query_plan.resource_types),
        "years": list(query_plan.years),
        "evidence_tasks": list(query_plan.evidence_tasks),
    }


def _version_fingerprint(version_basis: dict[str, Any]) -> str:
    payload = json.dumps(version_basis, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _counter_payload(counter: Counter[str], *, limit: int) -> list[dict[str, Any]]:
    return [{"value": value, "count": count} for value, count in counter.most_common(limit) if value]


def _clean_text(value: Any, *, max_chars: int = 120) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())[:max_chars]


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
