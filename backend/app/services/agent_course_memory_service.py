from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from typing import Any

from app.models.materials import MaterialRecord
from app.services.agent_memory_service import AgentMemoryContext
from app.services.agent_material_signal_service import build_material_signals
from app.services.agent_query_planner_service import AgentQueryPlan
from app.services.material_pdf_evidence_service import MaterialPageEvidence


@dataclass(slots=True)
class CourseMemoryCard:
    course: str
    version: str
    version_fingerprint: str
    version_basis: dict[str, Any]
    source: str
    evidence_coverage: dict[str, Any]
    confidence_assessment: dict[str, Any]
    years: tuple[str, ...]
    question_type_distribution: tuple[dict[str, Any], ...]
    knowledge_signals: tuple[dict[str, Any], ...]
    chapter_distribution: tuple[dict[str, Any], ...]
    solution_signal_distribution: tuple[dict[str, Any], ...]
    score_point_distribution: tuple[dict[str, Any], ...]
    difficulty_distribution: tuple[dict[str, Any], ...]
    visual_signal_distribution: tuple[dict[str, Any], ...]
    source_type_distribution: tuple[dict[str, Any], ...]
    material_quality_distribution: tuple[dict[str, Any], ...]
    material_risk_distribution: tuple[dict[str, Any], ...]
    yearly_question_type_matrix: tuple[dict[str, Any], ...]
    study_strategy_distribution: tuple[dict[str, Any], ...]
    high_signal_materials: tuple[dict[str, Any], ...]
    experience_materials: tuple[dict[str, Any], ...]
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
            "evidence_coverage": self.evidence_coverage,
            "confidence_assessment": self.confidence_assessment,
            "years": list(self.years),
            "question_type_distribution": list(self.question_type_distribution),
            "knowledge_signals": list(self.knowledge_signals),
            "chapter_distribution": list(self.chapter_distribution),
            "solution_signal_distribution": list(self.solution_signal_distribution),
            "score_point_distribution": list(self.score_point_distribution),
            "difficulty_distribution": list(self.difficulty_distribution),
            "visual_signal_distribution": list(self.visual_signal_distribution),
            "source_type_distribution": list(self.source_type_distribution),
            "material_quality_distribution": list(self.material_quality_distribution),
            "material_risk_distribution": list(self.material_risk_distribution),
            "yearly_question_type_matrix": list(self.yearly_question_type_matrix),
            "study_strategy_distribution": list(self.study_strategy_distribution),
            "high_signal_materials": list(self.high_signal_materials),
            "experience_materials": list(self.experience_materials),
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
        chapter_signals = _counter_payload(_chapter_counter(pdf_evidence, memory_context), limit=8)
        solution_signals = _counter_payload(_solution_signal_counter(pdf_evidence, memory_context), limit=8)
        score_points = _counter_payload(_score_point_counter(pdf_evidence), limit=8)
        difficulty_signals = _counter_payload(_difficulty_counter(pdf_evidence), limit=5)
        visual_signals = _counter_payload(_visual_counter(pdf_evidence), limit=5)
        source_types = _counter_payload(_source_type_counter(pdf_evidence, memory_context), limit=5)
        material_quality = _counter_payload(_material_quality_counter(materials, memory_context), limit=8)
        material_risk = _counter_payload(_material_risk_counter(materials, memory_context), limit=8)
        yearly_matrix = _yearly_question_type_matrix(pdf_evidence)
        study_strategies = _counter_payload(_study_strategy_counter(memory_context), limit=8)
        experience_materials = _experience_materials(memory_context)
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
            evidence_coverage=_evidence_coverage(materials, pdf_evidence, years, memory_context),
            confidence_assessment=_confidence_assessment(materials, pdf_evidence, years, question_types, memory_context),
            years=tuple(years),
            question_type_distribution=tuple(question_types),
            knowledge_signals=tuple(knowledge_signals),
            chapter_distribution=tuple(chapter_signals),
            solution_signal_distribution=tuple(solution_signals),
            score_point_distribution=tuple(score_points),
            difficulty_distribution=tuple(difficulty_signals),
            visual_signal_distribution=tuple(visual_signals),
            source_type_distribution=tuple(source_types),
            material_quality_distribution=tuple(material_quality),
            material_risk_distribution=tuple(material_risk),
            yearly_question_type_matrix=tuple(yearly_matrix),
            study_strategy_distribution=tuple(study_strategies),
            high_signal_materials=tuple(_high_signal_materials(materials)),
            experience_materials=tuple(experience_materials),
            page_references=tuple(_page_references(pdf_evidence)),
            recommended_sequence=tuple(_recommended_sequence(query_plan, bool(pdf_evidence), study_strategies)),
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


def _chapter_counter(
    pdf_evidence: list[MaterialPageEvidence],
    memory_context: AgentMemoryContext | None,
) -> Counter[str]:
    counter: Counter[str] = Counter()
    for evidence in pdf_evidence:
        counter.update(evidence.chapter_signals)
    if pdf_evidence:
        return counter
    platform = memory_context.platform if memory_context else {}
    for item in platform.get("pdf_chapter_signals") or []:
        if isinstance(item, dict) and item.get("value"):
            counter[str(item["value"])] += int(item.get("count") or 1)
    return counter


def _solution_signal_counter(
    pdf_evidence: list[MaterialPageEvidence],
    memory_context: AgentMemoryContext | None,
) -> Counter[str]:
    counter: Counter[str] = Counter()
    for evidence in pdf_evidence:
        counter.update(evidence.solution_signals)
    if pdf_evidence:
        return counter
    platform = memory_context.platform if memory_context else {}
    for item in platform.get("pdf_solution_signals") or []:
        if isinstance(item, dict) and item.get("value"):
            counter[str(item["value"])] += int(item.get("count") or 1)
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


def _visual_counter(pdf_evidence: list[MaterialPageEvidence]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for evidence in pdf_evidence:
        counter.update(evidence.visual_signals)
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
    for source_key in ("pdf_source_type_signals", "material_source_type_signals"):
        for item in platform.get(source_key) or []:
            if isinstance(item, dict) and item.get("value"):
                counter[str(item["value"])] += int(item.get("count") or 1)
    return counter


def _material_quality_counter(
    materials: list[MaterialRecord],
    memory_context: AgentMemoryContext | None,
) -> Counter[str]:
    counter: Counter[str] = Counter()
    for material in materials:
        counter.update(build_material_signals(material).quality_signals)
    platform = memory_context.platform if memory_context else {}
    for item in platform.get("material_quality_signals") or []:
        if isinstance(item, dict) and item.get("value"):
            counter[str(item["value"])] += int(item.get("count") or 1)
    return counter


def _material_risk_counter(
    materials: list[MaterialRecord],
    memory_context: AgentMemoryContext | None,
) -> Counter[str]:
    counter: Counter[str] = Counter()
    for material in materials:
        counter.update(build_material_signals(material).risk_signals)
    platform = memory_context.platform if memory_context else {}
    for item in platform.get("material_risk_signals") or []:
        if isinstance(item, dict) and item.get("value"):
            counter[str(item["value"])] += int(item.get("count") or 1)
    return counter


def _yearly_question_type_matrix(pdf_evidence: list[MaterialPageEvidence]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for evidence in pdf_evidence:
        for year in evidence.years:
            cleaned_year = _clean_text(year, max_chars=16)
            if not cleaned_year:
                continue
            bucket = buckets.setdefault(
                cleaned_year,
                {
                    "question_types": Counter(),
                    "knowledge_signals": Counter(),
                    "question_numbers": [],
                    "page_references": [],
                },
            )
            bucket["question_types"].update(evidence.question_types)
            bucket["knowledge_signals"].update(evidence.knowledge_signals)
            for number in evidence.question_numbers:
                cleaned_number = _clean_text(number, max_chars=24)
                if cleaned_number and cleaned_number not in bucket["question_numbers"]:
                    bucket["question_numbers"].append(cleaned_number)
            page_ref = {
                "material_id": int(evidence.material_id),
                "title": _clean_text(evidence.title),
                "page": int(evidence.page),
            }
            if page_ref not in bucket["page_references"]:
                bucket["page_references"].append(page_ref)
    matrix: list[dict[str, Any]] = []
    for year in sorted(buckets, reverse=True)[:8]:
        bucket = buckets[year]
        payload: dict[str, Any] = {
            "year": year,
            "question_types": _counter_payload(bucket["question_types"], limit=5),
            "knowledge_signals": _counter_payload(bucket["knowledge_signals"], limit=6),
            "question_numbers": bucket["question_numbers"][:6],
            "page_references": bucket["page_references"][:4],
        }
        matrix.append({key: value for key, value in payload.items() if value not in (None, [], {}, "")})
    return matrix


def _study_strategy_counter(memory_context: AgentMemoryContext | None) -> Counter[str]:
    counter: Counter[str] = Counter()
    platform = memory_context.platform if memory_context else {}
    for item in platform.get("study_strategy_signals") or []:
        if isinstance(item, dict) and item.get("value"):
            counter[str(item["value"])] += int(item.get("count") or 1)
    return counter


def _experience_materials(memory_context: AgentMemoryContext | None) -> list[dict[str, Any]]:
    platform = memory_context.platform if memory_context else {}
    result: list[dict[str, Any]] = []
    for item in platform.get("experience_materials") or []:
        if not isinstance(item, dict):
            continue
        material_id = _safe_int(item.get("material_id"))
        title = _clean_text(item.get("title"))
        if material_id is None or not title:
            continue
        payload: dict[str, Any] = {"material_id": material_id, "title": title}
        tags = _clean_text_list(item.get("tags"), limit=4)
        strategies = _clean_text_list(item.get("study_strategy_signals"), limit=4)
        quality = _clean_text_list(item.get("quality_signals"), limit=3)
        if tags:
            payload["tags"] = tags
        if strategies:
            payload["study_strategy_signals"] = strategies
        if quality:
            payload["quality_signals"] = quality
        result.append(payload)
        if len(result) >= 4:
            break
    return result


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


def _evidence_coverage(
    materials: list[MaterialRecord],
    pdf_evidence: list[MaterialPageEvidence],
    years: list[str],
    memory_context: AgentMemoryContext | None,
) -> dict[str, Any]:
    pdf_material_ids = {int(item.material_id) for item in pdf_evidence}
    question_numbers = _dedupe([number for item in pdf_evidence for number in item.question_numbers])
    source_types = _dedupe([item.source_type for item in pdf_evidence if item.source_type != "unknown"])
    platform_signal_keys = _platform_signal_keys(memory_context)
    payload: dict[str, Any] = {
        "candidate_material_count": len(materials),
        "pdf_evidence_page_count": len(pdf_evidence),
        "pdf_evidence_material_count": len(pdf_material_ids),
        "year_signal_count": len(years),
        "question_number_signal_count": len(question_numbers),
        "source_types": source_types[:5],
        "evidence_basis": _evidence_basis(pdf_evidence, platform_signal_keys),
    }
    return {key: value for key, value in payload.items() if value not in (None, [], {}, "")}


def _confidence_assessment(
    materials: list[MaterialRecord],
    pdf_evidence: list[MaterialPageEvidence],
    years: list[str],
    question_types: list[dict[str, Any]],
    memory_context: AgentMemoryContext | None,
) -> dict[str, Any]:
    signals: list[str] = []
    limitations: list[str] = []
    platform_signal_keys = _platform_signal_keys(memory_context)
    if len(materials) >= 3:
        signals.append("候选资料数量较充分")
    elif len(materials) <= 1:
        limitations.append("候选资料较少")
    if len({int(item.material_id) for item in pdf_evidence}) >= 2:
        signals.append("PDF 证据覆盖多份资料")
    elif pdf_evidence:
        limitations.append("PDF 证据主要来自单份资料")
    else:
        limitations.append("缺少 PDF 页级证据")
        if any(key.startswith("pdf_") for key in platform_signal_keys):
            limitations.append("题型和年份主要来自平台聚合信号，当前回答不能当作已读取原文页。")
        elif platform_signal_keys:
            limitations.append("当前课程记忆主要基于平台聚合元数据和候选资料元数据。")
        elif materials:
            limitations.append("当前课程记忆主要基于候选资料元数据。")
    if len(years) >= 3:
        signals.append("年份信号覆盖较多")
    elif years:
        limitations.append("年份信号有限")
    if len(question_types) >= 2:
        signals.append("题型信号较丰富")
    elif question_types:
        limitations.append("题型信号有限")

    if len(signals) >= 3 and not limitations:
        level = "high"
    elif pdf_evidence and (signals or len(materials) >= 2):
        level = "medium"
    else:
        level = "low"
    return {
        "level": level,
        "signals": signals[:5],
        "limitations": limitations[:5],
    }


def _platform_signal_keys(memory_context: AgentMemoryContext | None) -> list[str]:
    platform = memory_context.platform if memory_context else {}
    return sorted(str(key) for key, value in platform.items() if value not in (None, [], {}, ""))


def _evidence_basis(pdf_evidence: list[MaterialPageEvidence], platform_signal_keys: list[str]) -> str:
    if pdf_evidence:
        return "pdf_page_evidence"
    if platform_signal_keys:
        return "platform_collective_signals"
    return "candidate_metadata_only"


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
        if evidence.chapter_signals:
            payload["chapter_signals"] = list(evidence.chapter_signals)
        if evidence.solution_signals:
            payload["solution_signals"] = list(evidence.solution_signals)
        if evidence.score_points:
            payload["score_points"] = list(evidence.score_points)
        if evidence.difficulty_signals:
            payload["difficulty_signals"] = list(evidence.difficulty_signals)
        if evidence.visual_signals:
            payload["visual_signals"] = list(evidence.visual_signals)
        if evidence.anchor_terms:
            payload["anchor_terms"] = list(evidence.anchor_terms)
        if evidence.anchor_text:
            payload["anchor_text"] = evidence.anchor_text
        if evidence.source_type != "unknown":
            payload["source_type"] = evidence.source_type
        references.append(payload)
    return references


def _recommended_sequence(
    query_plan: AgentQueryPlan | None,
    has_pdf_evidence: bool,
    study_strategies: list[dict[str, Any]],
) -> list[str]:
    if query_plan and query_plan.intent == "exam_trend_analysis":
        base = ["先看高频题型", "再核对年份趋势", "最后按页码打开真题资料查漏补缺"]
    elif query_plan and query_plan.intent == "study_plan":
        base = ["先建立知识框架", "再刷真题或例题", "最后复盘错题和薄弱点"]
    elif has_pdf_evidence:
        base = ["先读已引用页码", "再看推荐资料全文", "最后根据追问细化题型"]
    else:
        base = ["先确认课程范围", "再筛选最相关资料", "最后补充题型或年份要求"]
    for item in study_strategies:
        if not isinstance(item, dict):
            continue
        value = _clean_text(item.get("value"))
        if value and value not in base:
            base.append(value)
        if len(base) >= 6:
            break
    return base


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
        "strategy_refs": _strategy_ref_basis(memory_context),
        "experience_material_ids": [item["material_id"] for item in _experience_materials(memory_context)],
        "quality_refs": _quality_ref_basis(materials, memory_context),
        "risk_refs": _risk_ref_basis(materials, memory_context),
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
    if item.chapter_signals:
        payload["chapter_signals"] = list(item.chapter_signals)
    if item.solution_signals:
        payload["solution_signals"] = list(item.solution_signals)
    if item.score_points:
        payload["score_points"] = list(item.score_points)
    if item.difficulty_signals:
        payload["difficulty_signals"] = list(item.difficulty_signals)
    if item.visual_signals:
        payload["visual_signals"] = list(item.visual_signals)
    if item.anchor_terms:
        payload["anchor_terms"] = list(item.anchor_terms)
    if item.anchor_text:
        payload["anchor_text"] = item.anchor_text
    return payload


def _query_plan_basis(query_plan: AgentQueryPlan | None) -> dict[str, Any]:
    if query_plan is None:
        return {}
    payload: dict[str, Any] = {
        "intent": query_plan.intent,
        "course_terms": list(query_plan.course_terms),
        "resource_types": list(query_plan.resource_types),
        "years": list(query_plan.years),
        "evidence_tasks": list(query_plan.evidence_tasks),
    }
    material_scope = getattr(query_plan, "material_scope", {})
    if isinstance(material_scope, dict) and material_scope:
        payload["material_scope"] = material_scope
    return payload


def _strategy_ref_basis(memory_context: AgentMemoryContext | None) -> list[str]:
    return [
        item["value"]
        for item in _counter_payload(_study_strategy_counter(memory_context), limit=8)
        if isinstance(item.get("value"), str)
    ]


def _quality_ref_basis(materials: list[MaterialRecord], memory_context: AgentMemoryContext | None) -> list[str]:
    return [
        item["value"]
        for item in _counter_payload(_material_quality_counter(materials, memory_context), limit=8)
        if isinstance(item.get("value"), str)
    ]


def _risk_ref_basis(materials: list[MaterialRecord], memory_context: AgentMemoryContext | None) -> list[str]:
    return [
        item["value"]
        for item in _counter_payload(_material_risk_counter(materials, memory_context), limit=8)
        if isinstance(item.get("value"), str)
    ]


def _version_fingerprint(version_basis: dict[str, Any]) -> str:
    payload = json.dumps(version_basis, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _counter_payload(counter: Counter[str], *, limit: int) -> list[dict[str, Any]]:
    return [{"value": value, "count": count} for value, count in counter.most_common(limit) if value]


def _clean_text(value: Any, *, max_chars: int = 120) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())[:max_chars]


def _clean_text_list(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        cleaned = _clean_text(item)
        if cleaned and cleaned not in result:
            result.append(cleaned)
        if len(result) >= limit:
            break
    return result


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
