from __future__ import annotations

from typing import Any

from app.agentic_platform.domain.plan import RetryPolicy
from app.services.agent_material_signal_service import build_material_signals, safe_material_value
from app.services.materials_serializers import load_json_list

from ..base import BaseSkill, IdempotencyMode, ObservationTrainingRole, SkillCost, SkillSpec
from ..context import SkillExecutionContext
from ..executor import SkillExecutionError
from .schemas import (
    CompareMaterialsInput,
    CompareMaterialsOutput,
    FindAnswerPagesInput,
    FindAnswerPagesOutput,
    FindQuestionPagesInput,
    FindQuestionPagesOutput,
    MaterialComparison,
    MaterialInspectInput,
    MaterialInspectOutput,
    MaterialPageEvidenceOutput,
    MaterialSearchInput,
    MaterialSearchOutput,
    MaterialSummary,
    ReadPdfEvidenceInput,
    ReadPdfEvidenceOutput,
)


MATERIAL_READ_SCOPES = ["agentic.admin", "materials.read"]
MATERIAL_RETRY_POLICY = RetryPolicy(max_attempts=2, retryable_error_codes=["timeout", "transient"])


def _material_summary_from_mapping(item: dict[str, Any]) -> MaterialSummary:
    material_id = int(item["id"])
    signals = item.get("signals") if isinstance(item.get("signals"), dict) else {}
    return MaterialSummary(
        material_id=material_id,
        title=str(item.get("title") or f"资料 #{material_id}")[:120],
        description=_clean_optional_text(item.get("description"), 1_000),
        tags=_clean_string_list(item.get("tags"), 20, 80),
        is_free=bool(item.get("free", item.get("isFree", True))),
        school=_clean_optional_text(item.get("school"), 120),
        college=_clean_optional_text(item.get("college"), 120),
        major=_clean_optional_text(item.get("major"), 255),
        course_category=_clean_optional_text(item.get("courseCategory"), 32),
        rating_avg=max(0.0, _as_float(item.get("ratingAvg", item.get("rating_avg")), 0.0)),
        rating_count=max(0, _as_int(item.get("ratingCount", item.get("rating_count")), 0)),
        download_count=max(0, _as_int(item.get("downloadCount", item.get("download_count")), 0)),
        quality_signals=_clean_string_list(signals.get("quality_signals"), 8, 80),
        risk_signals=_clean_string_list(signals.get("risk_signals"), 8, 80),
    )


def _material_summary_from_record(material: Any) -> MaterialSummary:
    material_id = _as_int(safe_material_value(material, "id"), 0)
    if material_id <= 0:
        raise SkillExecutionError("material record is missing a positive ID", code="invalid_material_record")
    signals = build_material_signals(material)
    return MaterialSummary(
        material_id=material_id,
        title=_clean_optional_text(safe_material_value(material, "title"), 120) or f"资料 #{material_id}",
        description=_clean_optional_text(safe_material_value(material, "description"), 1_000),
        tags=_clean_string_list(load_json_list(safe_material_value(material, "tags_json")), 20, 80),
        is_free=bool(safe_material_value(material, "is_free", True)),
        school=_clean_optional_text(safe_material_value(material, "school"), 120),
        college=_clean_optional_text(safe_material_value(material, "college"), 120),
        major=_clean_optional_text(safe_material_value(material, "major"), 255),
        course_category=_clean_optional_text(safe_material_value(material, "course_category"), 32),
        rating_avg=max(0.0, _as_float(safe_material_value(material, "rating_avg"), 0.0)),
        rating_count=max(0, _as_int(safe_material_value(material, "rating_count"), 0)),
        download_count=max(0, _as_int(safe_material_value(material, "download_count"), 0)),
        quality_signals=list(signals.quality_signals),
        risk_signals=list(signals.risk_signals),
    )


def _evidence_output(item: Any) -> MaterialPageEvidenceOutput:
    return MaterialPageEvidenceOutput(
        evidence_id=str(item.evidence_id()),
        material_id=int(item.material_id),
        title=str(item.title)[:120],
        page=int(item.page),
        excerpt=str(item.text)[:700],
        question_types=_clean_string_list(item.question_types, 8, 80),
        question_numbers=_clean_string_list(item.question_numbers, 12, 80),
        source_type=str(item.source_type or "unknown")[:64],
        solution_signals=_clean_string_list(item.solution_signals, 8, 80),
        anchor_terms=_clean_string_list(item.anchor_terms, 8, 80),
    )


def _load_materials(context: SkillExecutionContext, material_ids: list[int]) -> tuple[list[Any], list[int]]:
    session = context.require_live_session()
    repository = context.require_material_repo()
    loaded = repository.list_materials_by_ids(session, material_ids)
    by_id = {_as_int(safe_material_value(material, "id"), 0): material for material in loaded}
    materials = [by_id[material_id] for material_id in material_ids if material_id in by_id]
    missing = [material_id for material_id in material_ids if material_id not in by_id]
    return materials, missing


def _load_pdf_evidence(context: SkillExecutionContext, payload: ReadPdfEvidenceInput) -> tuple[list[MaterialPageEvidenceOutput], list[int]]:
    materials, missing = _load_materials(context, payload.material_ids)
    if not materials:
        return [], missing
    service = context.require_pdf_evidence_service()
    try:
        evidence = service.collect_for_materials(
            materials,
            payload.query,
            current_user_id=context.current_user_id or context.admin_actor_id,
            current_user_role_mask=context.current_user_role_mask
            if context.current_user_role_mask is not None
            else context.role_mask,
            force=True,
            max_materials=len(materials),
            max_results=payload.max_pages,
            page_numbers=set(payload.page_numbers) or None,
        )
    except Exception as exc:  # noqa: BLE001
        raise SkillExecutionError("PDF evidence collection failed", code="transient", retryable=True) from exc
    return [_evidence_output(item) for item in evidence], missing


class SearchMaterialsSkill(BaseSkill[MaterialSearchInput, MaterialSearchOutput]):
    input_model = MaterialSearchInput
    output_model = MaterialSearchOutput
    spec = SkillSpec(
        name="materials.search",
        version="1.0",
        description="Search visible StudyHub materials through the existing MaterialsService.",
        input_model="MaterialSearchInput",
        output_model="MaterialSearchOutput",
        side_effect="read",
        permission_scopes=MATERIAL_READ_SCOPES,
        timeout_seconds=12.0,
        retry_policy=MATERIAL_RETRY_POLICY,
        idempotency=IdempotencyMode.PURE,
        observation_training_role=ObservationTrainingRole.VISIBLE_MASKED,
        environment_adapter="live_studyhub",
        reward_hooks=["candidate_rank_delta"],
        cost_model=SkillCost(estimated_context_tokens=400),
    )

    async def execute(self, context: SkillExecutionContext, payload: MaterialSearchInput) -> MaterialSearchOutput:
        session = context.require_live_session()
        if context.materials_service is None:
            raise SkillExecutionError("materials.search requires MaterialsService", code="dependency_unavailable")
        filters = payload.filters
        response = context.materials_service.list_materials(
            session,
            context.current_user_id or context.admin_actor_id,
            keyword=payload.query,
            school=filters.school,
            college=filters.college,
            major=filters.major,
            tag=filters.tag,
            grade_value=None,
            course_category=None,
            price=None,
            sort="relevance",
            page=1,
            size=payload.limit,
        )
        items = response.get("items") if isinstance(response, dict) else []
        materials = [_material_summary_from_mapping(item) for item in items if isinstance(item, dict)]
        return MaterialSearchOutput(
            query=payload.query,
            materials=materials,
            count=len(materials),
            retrieval_engine="materials_service.search",
        )


class InspectMaterialsSkill(BaseSkill[MaterialInspectInput, MaterialInspectOutput]):
    input_model = MaterialInspectInput
    output_model = MaterialInspectOutput
    spec = SkillSpec(
        name="materials.inspect",
        version="1.0",
        description="Inspect selected material metadata through MaterialRepository.",
        input_model="MaterialInspectInput",
        output_model="MaterialInspectOutput",
        side_effect="read",
        permission_scopes=MATERIAL_READ_SCOPES,
        timeout_seconds=8.0,
        retry_policy=MATERIAL_RETRY_POLICY,
        idempotency=IdempotencyMode.PURE,
        observation_training_role=ObservationTrainingRole.VISIBLE_MASKED,
        environment_adapter="live_studyhub",
        reward_hooks=["candidate_rank_delta"],
        cost_model=SkillCost(estimated_context_tokens=500),
    )

    async def execute(self, context: SkillExecutionContext, payload: MaterialInspectInput) -> MaterialInspectOutput:
        materials, missing = _load_materials(context, payload.material_ids)
        return MaterialInspectOutput(
            materials=[_material_summary_from_record(material) for material in materials],
            missing_material_ids=missing,
        )


class ReadPdfEvidenceSkill(BaseSkill[ReadPdfEvidenceInput, ReadPdfEvidenceOutput]):
    input_model = ReadPdfEvidenceInput
    output_model = ReadPdfEvidenceOutput
    spec = SkillSpec(
        name="materials.read_pdf_evidence",
        version="1.0",
        description="Read administrator-authorized page evidence through MaterialPdfEvidenceService.",
        input_model="ReadPdfEvidenceInput",
        output_model="ReadPdfEvidenceOutput",
        side_effect="read",
        permission_scopes=MATERIAL_READ_SCOPES,
        timeout_seconds=20.0,
        retry_policy=MATERIAL_RETRY_POLICY,
        idempotency=IdempotencyMode.PURE,
        observation_training_role=ObservationTrainingRole.VISIBLE_MASKED,
        environment_adapter="live_studyhub",
        reward_hooks=["evidence_added", "citation_supported"],
        cost_model=SkillCost(estimated_context_tokens=1_200),
    )

    async def execute(self, context: SkillExecutionContext, payload: ReadPdfEvidenceInput) -> ReadPdfEvidenceOutput:
        evidence, missing = _load_pdf_evidence(context, payload)
        reason = "no_authorized_evidence" if not evidence else None
        if missing and not evidence:
            reason = "materials_not_found"
        return ReadPdfEvidenceOutput(available=bool(evidence), evidence=evidence, reason=reason)


class FindQuestionPagesSkill(BaseSkill[FindQuestionPagesInput, FindQuestionPagesOutput]):
    input_model = FindQuestionPagesInput
    output_model = FindQuestionPagesOutput
    spec = SkillSpec(
        name="materials.find_question_pages",
        version="1.0",
        description="Find PDF pages carrying question-number or question-type evidence.",
        input_model="FindQuestionPagesInput",
        output_model="FindQuestionPagesOutput",
        side_effect="read",
        permission_scopes=MATERIAL_READ_SCOPES,
        timeout_seconds=20.0,
        retry_policy=MATERIAL_RETRY_POLICY,
        idempotency=IdempotencyMode.PURE,
        observation_training_role=ObservationTrainingRole.VISIBLE_MASKED,
        environment_adapter="live_studyhub",
        reward_hooks=["evidence_added"],
        cost_model=SkillCost(estimated_context_tokens=1_000),
    )

    async def execute(self, context: SkillExecutionContext, payload: FindQuestionPagesInput) -> FindQuestionPagesOutput:
        evidence, _missing = _load_pdf_evidence(context, payload)
        pages = [
            item
            for item in evidence
            if item.source_type != "answer_explanation"
            and (item.question_types or item.question_numbers or item.source_type in {"past_exam", "exercise"})
        ]
        return FindQuestionPagesOutput(pages=pages)


class FindAnswerPagesSkill(BaseSkill[FindAnswerPagesInput, FindAnswerPagesOutput]):
    input_model = FindAnswerPagesInput
    output_model = FindAnswerPagesOutput
    spec = SkillSpec(
        name="materials.find_answer_pages",
        version="1.0",
        description="Find PDF pages carrying answer or solution evidence.",
        input_model="FindAnswerPagesInput",
        output_model="FindAnswerPagesOutput",
        side_effect="read",
        permission_scopes=MATERIAL_READ_SCOPES,
        timeout_seconds=20.0,
        retry_policy=MATERIAL_RETRY_POLICY,
        idempotency=IdempotencyMode.PURE,
        observation_training_role=ObservationTrainingRole.VISIBLE_MASKED,
        environment_adapter="live_studyhub",
        reward_hooks=["evidence_added", "citation_supported"],
        cost_model=SkillCost(estimated_context_tokens=1_000),
    )

    async def execute(self, context: SkillExecutionContext, payload: FindAnswerPagesInput) -> FindAnswerPagesOutput:
        evidence, _missing = _load_pdf_evidence(context, payload)
        pages = [
            item
            for item in evidence
            if item.solution_signals or item.source_type == "answer_explanation"
        ]
        return FindAnswerPagesOutput(pages=pages)


class CompareMaterialsSkill(BaseSkill[CompareMaterialsInput, CompareMaterialsOutput]):
    input_model = CompareMaterialsInput
    output_model = CompareMaterialsOutput
    spec = SkillSpec(
        name="materials.compare",
        version="1.0",
        description="Compare selected materials with repository metadata and existing quality signals.",
        input_model="CompareMaterialsInput",
        output_model="CompareMaterialsOutput",
        side_effect="read",
        permission_scopes=MATERIAL_READ_SCOPES,
        timeout_seconds=8.0,
        retry_policy=MATERIAL_RETRY_POLICY,
        idempotency=IdempotencyMode.PURE,
        observation_training_role=ObservationTrainingRole.VISIBLE_MASKED,
        environment_adapter="live_studyhub",
        reward_hooks=["candidate_rank_delta"],
        cost_model=SkillCost(estimated_context_tokens=600),
    )

    async def execute(self, context: SkillExecutionContext, payload: CompareMaterialsInput) -> CompareMaterialsOutput:
        materials, missing = _load_materials(context, payload.material_ids)
        comparisons = []
        for material in materials:
            summary = _material_summary_from_record(material)
            comparisons.append(
                MaterialComparison(
                    material_id=summary.material_id,
                    title=summary.title,
                    is_free=summary.is_free,
                    tags=summary.tags,
                    rating_avg=summary.rating_avg,
                    download_count=summary.download_count,
                    quality_signals=summary.quality_signals,
                    risk_signals=summary.risk_signals,
                )
            )
        return CompareMaterialsOutput(comparisons=comparisons, missing_material_ids=missing)


def _clean_optional_text(value: object, max_length: int) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).split()).strip()[:max_length]
    return normalized or None


def _clean_string_list(value: object, limit: int, max_length: int) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[str] = []
    for item in value:
        cleaned = _clean_optional_text(item, max_length)
        if cleaned and cleaned not in result:
            result.append(cleaned)
        if len(result) >= limit:
            break
    return result


def _as_int(value: object, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _as_float(value: object, default: float) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
