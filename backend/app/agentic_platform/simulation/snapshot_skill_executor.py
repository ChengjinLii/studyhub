"""Dynamic typed Skill execution over a frozen ``StudyHubWorldSnapshot``."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from pydantic import BaseModel

from app.agentic_platform.deepresearch.domain_router import ResearchCapabilityFlags, ResearchEnvironmentError
from app.agentic_platform.domain.artifact import ArtifactKind
from app.agentic_platform.domain.decision import AgentActionType, AgentDecision
from app.agentic_platform.domain.hashing import canonical_hash
from app.agentic_platform.domain.observation import Observation, ObservationSource
from app.agentic_platform.domain.reward_facts import RewardFacts
from app.agentic_platform.domain.state import AgentTaskState, StateDelta
from app.agentic_platform.domain.transition import ExecutionError, VerifierResult
from app.agentic_platform.skills.context import SkillExecutionContext, SkillExecutionMode
from app.agentic_platform.skills.executor import SkillExecutionError, SkillExecutor
from app.agentic_platform.skills.materials.schemas import (
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
from app.agentic_platform.skills.registry import SkillRegistry
from app.agentic_platform.simulation.environment import EnvironmentActionExecutor, EnvironmentActionResult
from app.services.read_support import ROLE_ADMIN

from .snapshot_research_environment import SnapshotResearchEnvironment
from .world_snapshot import StudyHubWorldSnapshot, WorldSnapshotArtifactStore


class SnapshotSkillExecutor(SkillExecutor):
    """Execute registered read/validation/research Skills against frozen data.

    The execution is selected by the requested Skill name and typed arguments,
    not by an expected-action hash.  This means a model may formulate a new
    valid query or candidate list while the resulting world observations remain
    deterministic for the same snapshot and seed.
    """

    def __init__(
        self,
        registry: SkillRegistry,
        *,
        snapshot: StudyHubWorldSnapshot,
        artifact_store: WorldSnapshotArtifactStore,
        seed: int | None = None,
    ) -> None:
        super().__init__(registry)
        self.snapshot = snapshot.model_copy(deep=True)
        self.artifact_store = artifact_store
        self.research_environment = SnapshotResearchEnvironment(snapshot, artifact_store, seed=seed)

    async def _invoke(self, skill, context: SkillExecutionContext, payload: BaseModel) -> BaseModel:
        if context.mode != SkillExecutionMode.SNAPSHOT:
            raise SkillExecutionError("snapshot executor received a non-snapshot context", code="execution_mode_mismatch")
        name = skill.spec.name
        material_handlers = {
            "materials.search": self._search_materials,
            "materials.inspect": self._inspect_materials,
            "materials.read_pdf_evidence": self._read_pdf_evidence,
            "materials.find_question_pages": self._find_question_pages,
            "materials.find_answer_pages": self._find_answer_pages,
            "materials.compare": self._compare_materials,
        }
        handler = material_handlers.get(name)
        if handler is not None:
            return await handler(payload)
        if name.startswith("research."):
            snapshot_context = replace(
                context,
                research_environment=self.research_environment,
                research_capability_flags=ResearchCapabilityFlags(web_enabled=False, scholar_enabled=False),
            )
            return await skill.execute(snapshot_context, payload)
        if name.startswith("validation."):
            return await skill.execute(context, payload)
        raise SkillExecutionError("Skill is unavailable in this snapshot environment", code="snapshot_skill_unsupported")

    async def _search_materials(self, payload: BaseModel) -> MaterialSearchOutput:
        assert isinstance(payload, MaterialSearchInput)
        material_ids = self.research_environment.ranked_material_ids(payload.query, limit=12)
        materials = [
            self._material_summary(material_id)
            for material_id in material_ids
            if self._matches_filters(material_id, payload.filters.model_dump(mode="python"))
        ][: payload.limit]
        return MaterialSearchOutput(
            query=payload.query,
            materials=materials,
            count=len(materials),
            retrieval_engine=f"snapshot:{self.research_environment.world.retriever.retriever_version}",
        )

    async def _inspect_materials(self, payload: BaseModel) -> MaterialInspectOutput:
        assert isinstance(payload, MaterialInspectInput)
        materials: list[MaterialSummary] = []
        missing: list[int] = []
        for material_id in payload.material_ids:
            if self.research_environment.material(material_id) is None or not self.research_environment.is_material_allowed(material_id):
                missing.append(material_id)
            else:
                materials.append(self._material_summary(material_id))
        return MaterialInspectOutput(materials=materials, missing_material_ids=missing)

    async def _read_pdf_evidence(self, payload: BaseModel) -> ReadPdfEvidenceOutput:
        assert isinstance(payload, ReadPdfEvidenceInput)
        try:
            evidence = await self.research_environment.read_internal(
                [f"material:{material_id}" for material_id in payload.material_ids],
                payload.query,
                page_limit=payload.max_pages,
            )
        except ResearchEnvironmentError as exc:
            return ReadPdfEvidenceOutput(available=False, evidence=[], reason=exc.code)
        page_filter = set(payload.page_numbers)
        values = [
            self._page_evidence(item.material_id or 0, item.page or 0)
            for item in evidence
            if not page_filter or (item.page is not None and item.page in page_filter)
        ]
        return ReadPdfEvidenceOutput(
            available=bool(values),
            evidence=values,
            reason=None if values else "no_matching_snapshot_evidence",
        )

    async def _find_question_pages(self, payload: BaseModel) -> FindQuestionPagesOutput:
        assert isinstance(payload, FindQuestionPagesInput)
        result = await self._read_pdf_evidence(payload)
        return FindQuestionPagesOutput(
            pages=[
                item
                for item in result.evidence
                if item.question_types or item.question_numbers or item.source_type in {"past_exam", "exercise"}
            ]
        )

    async def _find_answer_pages(self, payload: BaseModel) -> FindAnswerPagesOutput:
        assert isinstance(payload, FindAnswerPagesInput)
        result = await self._read_pdf_evidence(payload)
        return FindAnswerPagesOutput(
            pages=[item for item in result.evidence if item.solution_signals or item.source_type == "answer_explanation"]
        )

    async def _compare_materials(self, payload: BaseModel) -> CompareMaterialsOutput:
        assert isinstance(payload, CompareMaterialsInput)
        comparisons: list[MaterialComparison] = []
        missing: list[int] = []
        for material_id in payload.material_ids:
            if self.research_environment.material(material_id) is None or not self.research_environment.is_material_allowed(material_id):
                missing.append(material_id)
                continue
            summary = self._material_summary(material_id)
            comparisons.append(
                MaterialComparison(
                    material_id=summary.material_id,
                    title=summary.title,
                    is_free=summary.is_free,
                    tags=list(summary.tags),
                    rating_avg=summary.rating_avg,
                    download_count=summary.download_count,
                    quality_signals=list(summary.quality_signals),
                    risk_signals=list(summary.risk_signals),
                )
            )
        return CompareMaterialsOutput(comparisons=comparisons, missing_material_ids=missing)

    def _material_summary(self, material_id: int) -> MaterialSummary:
        material = self.research_environment.material(material_id)
        if material is None or not self.research_environment.is_material_allowed(material_id):
            raise SkillExecutionError("material is not available in this snapshot", code="snapshot_material_unavailable")
        return MaterialSummary(
            material_id=material.material_id,
            title=material.title,
            description=material.description,
            tags=list(material.tags),
            is_free=material.is_free,
            school=material.school,
            college=material.college,
            major=material.major,
            course_category=material.course_category,
            rating_avg=material.rating_avg,
            rating_count=material.rating_count,
            download_count=material.download_count,
            quality_signals=list(material.quality_signals),
            risk_signals=list(material.risk_signals),
        )

    def _page_evidence(self, material_id: int, page_number: int) -> MaterialPageEvidenceOutput:
        page = self.research_environment.pdf_page(material_id, page_number)
        if page is None or page.corrupt or page.excerpt is None:
            raise SkillExecutionError("snapshot PDF page is unavailable", code="pdf_corrupt")
        return MaterialPageEvidenceOutput(
            evidence_id=f"snapshot-evidence-{material_id}-{page_number}",
            material_id=material_id,
            title=page.title,
            page=page_number,
            excerpt=page.excerpt,
            question_types=list(page.question_types),
            question_numbers=list(page.question_numbers),
            source_type=page.source_type,
            solution_signals=list(page.solution_signals),
            anchor_terms=list(page.anchor_terms),
        )

    def _matches_filters(self, material_id: int, filters: dict[str, Any]) -> bool:
        material = self.research_environment.material(material_id)
        if material is None:
            return False
        for field_name in ("school", "college", "major"):
            expected = filters.get(field_name)
            actual = getattr(material, field_name)
            if expected is not None and (actual or "").casefold() != str(expected).casefold():
                return False
        tag = filters.get("tag")
        return tag is None or str(tag).casefold() in {item.casefold() for item in material.tags}


class SnapshotEnvironmentActionExecutor(EnvironmentActionExecutor):
    """Open environment adapter that turns a valid Skill decision into a snapshot step."""

    def __init__(
        self,
        registry: SkillRegistry,
        *,
        snapshot: StudyHubWorldSnapshot,
        artifact_store: WorldSnapshotArtifactStore,
        permission_scopes: frozenset[str] | None = None,
    ) -> None:
        self.registry = registry
        self.snapshot = snapshot.model_copy(deep=True)
        self.artifact_store = artifact_store
        self.permission_scopes = permission_scopes or frozenset(
            scope for skill in registry.list() for scope in skill.spec.permission_scopes
        )

    async def execute(
        self,
        *,
        state: AgentTaskState,
        action: AgentDecision,
        scenario,
        seed: int,
        action_index: int,
    ) -> EnvironmentActionResult:
        del scenario, action_index
        if action.action_type != AgentActionType.EXECUTE_SKILL or action.skill_name is None or action.arguments is None:
            return EnvironmentActionResult(
                error=ExecutionError(
                    code="snapshot_action_unsupported",
                    summary="Snapshot environment supports registered Skill actions only.",
                    retryable=False,
                )
            )
        executor = SnapshotSkillExecutor(
            self.registry,
            snapshot=self.snapshot,
            artifact_store=self.artifact_store,
            seed=seed,
        )
        context = SkillExecutionContext(
            admin_actor_id=state.admin_actor_id,
            role_mask=ROLE_ADMIN,
            permission_scopes=self.permission_scopes,
            idempotency_key=f"snapshot:{self.snapshot.snapshot_id}:{canonical_hash(action)[:32]}",
            current_user_id=state.admin_actor_id,
            current_user_role_mask=ROLE_ADMIN,
            mode=SkillExecutionMode.SNAPSHOT,
        )
        try:
            result = await executor.execute(skill_name=action.skill_name, arguments=action.arguments, context=context)
        except SkillExecutionError as exc:
            return EnvironmentActionResult(
                error=ExecutionError(code=exc.code, summary="Snapshot Skill execution failed.", retryable=exc.retryable)
            )
        output = result.output.model_dump(mode="json")
        reference = self.artifact_store.put_json(
            artifact_type=ArtifactKind.OBSERVATION.value,
            payload={
                "schema_version": "1.0",
                "snapshot_id": self.snapshot.snapshot_id,
                "seed": seed,
                "skill_name": action.skill_name,
                "arguments_hash": canonical_hash(action.arguments, exclude_fields=()),
                "output": output,
            },
            summary=f"Frozen typed output from {action.skill_name}",
        )
        candidate_ids = _candidate_ids_from_output(output)
        evidence_added = _evidence_count_from_output(output)
        delta = StateDelta(
            candidate_ids_to_add=candidate_ids,
            evidence_refs_to_add=[reference] if evidence_added else [],
            artifact_refs_to_add=[reference],
        )
        return EnvironmentActionResult(
            state_delta=delta,
            observation=Observation(
                observation_id=f"snapshot-observation-{canonical_hash({'snapshot': self.snapshot.snapshot_id, 'seed': seed, 'action': action})[:32]}",
                source=ObservationSource.SKILL,
                summary=f"Snapshot Skill {action.skill_name} returned {result.output.__class__.__name__}.",
                artifact_ref=reference,
            ),
            verifier_result=VerifierResult(passed=True, summary="Snapshot Skill output is schema-valid."),
            reward_facts=RewardFacts(evidence_added=evidence_added, tool_cost=result.estimated_cost),
        )


def _candidate_ids_from_output(output: dict[str, Any]) -> list[str]:
    materials = output.get("materials")
    if not isinstance(materials, list):
        return []
    values: list[str] = []
    for material in materials:
        if isinstance(material, dict) and isinstance(material.get("material_id"), int):
            values.append(f"material:{material['material_id']}")
    return list(dict.fromkeys(values))


def _evidence_count_from_output(output: dict[str, Any]) -> int:
    evidence = output.get("evidence", output.get("pages", []))
    return len(evidence) if isinstance(evidence, list) else 0
