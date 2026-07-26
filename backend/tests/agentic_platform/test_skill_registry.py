from __future__ import annotations

import asyncio

import pytest
from pydantic import Field

from app.agentic_platform.domain import DomainModel
from app.agentic_platform.domain.plan import RetryPolicy
from app.agentic_platform.deepresearch.state import ResearchPlan, ResearchSection, ResearchTaskPacket, initial_research_state
from app.agentic_platform.skills.base import BaseSkill, IdempotencyMode, ObservationTrainingRole, SkillCost, SkillSpec
from app.agentic_platform.skills.context import SkillExecutionContext, SkillExecutionMode
from app.agentic_platform.skills.executor import (
    FixtureSkillExecutor,
    LiveSkillExecutor,
    SkillExecutionError,
    SkillInvalidArgumentsError,
    SkillPermissionDeniedError,
    SkillTimeoutError,
)
from app.agentic_platform.skills.registry import SkillRegistry, build_default_skill_registry
from app.api.deps import clear_dependency_caches, get_agentic_skill_registry


ALL_SKILL_SCOPES = frozenset(
    {
        "agentic.admin",
        "materials.read",
        "interaction.ask_admin",
        "validation.run",
        "research.internal",
        "research.web",
        "research.scholar",
        "research.analysis",
    }
)
BASE_SKILL_NAMES = (
    "interaction.ask_admin",
    "materials.compare",
    "materials.find_answer_pages",
    "materials.find_question_pages",
    "materials.inspect",
    "materials.read_pdf_evidence",
    "materials.search",
    "validation.check_constraints",
    "validation.check_artifact",
    "validation.check_evidence",
)
RESEARCH_SKILL_NAMES = (
    "research.cross_validate",
    "research.extract_claims",
    "research.manage_context",
    "research.plan",
    "research.read_internal",
    "research.read_web",
    "research.search_internal",
    "research.search_scholar",
    "research.search_web",
    "research.update_evidence",
    "research.validate_report",
    "research.write_report",
)
EXPECTED_SKILL_NAMES = tuple(sorted((*BASE_SKILL_NAMES, *RESEARCH_SKILL_NAMES)))


def _research_state_payload() -> dict[str, object]:
    return initial_research_state(
        ResearchTaskPacket(
            task_id="research-skill-fixture",
            admin_actor_id=3,
            research_question="What does the internal material show?",
        )
    ).model_dump(mode="json")


def _research_plan_payload() -> dict[str, object]:
    return ResearchPlan(
        plan_id="research-skill-plan",
        version=1,
        outline=[ResearchSection(section_id="findings", title="Findings", objective="Summarize evidence")],
        rationale_summary="Fixture plan.",
    ).model_dump(mode="json")


VALID_ARGUMENTS = {
    "materials.search": {"query": "通信原理 真题"},
    "materials.inspect": {"material_ids": [1]},
    "materials.read_pdf_evidence": {"material_ids": [1], "query": "计算题"},
    "materials.find_question_pages": {"material_ids": [1], "query": "计算题"},
    "materials.find_answer_pages": {"material_ids": [1], "query": "答案"},
    "materials.compare": {"material_ids": [1, 2]},
    "interaction.ask_admin": {"request_id": "request-1", "prompt": "Choose a scope"},
    "validation.check_constraints": {
        "constraints": [{"constraint_id": "constraint-1", "description": "Use evidence"}],
    },
    "validation.check_evidence": {"evidence": [], "required_claim_ids": []},
    "validation.check_artifact": {"artifact": {"artifact_type": "unknown"}},
    "research.plan": {"state": _research_state_payload(), "plan": _research_plan_payload()},
    "research.search_internal": {"state": _research_state_payload(), "query": "sampling"},
    "research.read_internal": {"state": _research_state_payload(), "source_ids": ["material:1"]},
    "research.search_web": {"state": _research_state_payload(), "query": "sampling"},
    "research.read_web": {"state": _research_state_payload(), "source_ids": ["web:1"]},
    "research.search_scholar": {"state": _research_state_payload(), "query": "sampling"},
    "research.extract_claims": {"state": _research_state_payload(), "claim_candidates": ["A claim"]},
    "research.update_evidence": {"state": _research_state_payload()},
    "research.cross_validate": {"state": _research_state_payload()},
    "research.manage_context": {"state": _research_state_payload(), "context_action": "compress"},
    "research.write_report": {"state": _research_state_payload(), "report_title": "Fixture report"},
    "research.validate_report": {"state": _research_state_payload()},
}


FIXTURE_OUTPUTS = {
    "materials.search": {
        "query": "通信原理 真题",
        "materials": [],
        "retrieval_engine": "fixture",
        "count": 0,
    },
    "materials.inspect": {"materials": [], "missing_material_ids": [1]},
    "materials.read_pdf_evidence": {"available": False, "evidence": [], "reason": "fixture_empty"},
    "materials.find_question_pages": {"pages": []},
    "materials.find_answer_pages": {"pages": []},
    "materials.compare": {"comparisons": [], "missing_material_ids": [1, 2]},
    "interaction.ask_admin": {
        "request": {"request_id": "request-1", "prompt": "Choose a scope", "choices": [], "required": True, "expires_at": None}
    },
    "validation.check_constraints": {
        "valid": True,
        "resolved_constraint_ids": [],
        "unresolved_constraint_ids": ["constraint-1"],
        "violations": [],
    },
    "validation.check_evidence": {
        "valid": True,
        "supported_claim_ids": [],
        "unsupported_claim_ids": [],
        "invalid_evidence_ids": [],
    },
    "validation.check_artifact": {
        "valid": False,
        "artifact_type": "unknown",
        "artifact_id": "unidentified",
        "violations": ["invalid_artifact"],
    },
    **{
        skill_name: {"delta": {}, "summary": "fixture research output", "error_code": None, "recoverable": False}
        for skill_name in RESEARCH_SKILL_NAMES
    },
}


def _fixture_context(*, role_mask: int = 8, scopes: frozenset[str] = ALL_SKILL_SCOPES) -> SkillExecutionContext:
    return SkillExecutionContext(
        admin_actor_id=3,
        role_mask=role_mask,
        permission_scopes=scopes,
        idempotency_key="fixture-key",
        mode=SkillExecutionMode.FIXTURE,
        fixture_outputs=FIXTURE_OUTPUTS,
    )


def test_default_registry_contains_exact_first_batch_with_strict_schemas() -> None:
    registry = build_default_skill_registry()

    assert registry.names() == EXPECTED_SKILL_NAMES
    for skill in registry.list():
        assert skill.spec.input_model == skill.input_model.__name__
        assert skill.spec.output_model == skill.output_model.__name__
        assert skill.input_model.model_json_schema()["additionalProperties"] is False
        assert skill.output_model.model_json_schema()["additionalProperties"] is False
        assert skill.spec.permission_scopes


def test_dependency_registry_is_dormant_and_rebuildable_without_enabling_routes() -> None:
    first = get_agentic_skill_registry()
    clear_dependency_caches()
    second = get_agentic_skill_registry()

    assert first.names() == EXPECTED_SKILL_NAMES
    assert second.names() == EXPECTED_SKILL_NAMES
    assert first is not second


def test_fixture_executor_gives_every_first_batch_skill_a_typed_happy_and_empty_output() -> None:
    registry = build_default_skill_registry()
    executor = FixtureSkillExecutor(registry)
    context = _fixture_context()

    for skill_name in EXPECTED_SKILL_NAMES:
        result = asyncio.run(executor.execute(skill_name=skill_name, arguments=VALID_ARGUMENTS[skill_name], context=context))
        skill = registry.get(skill_name)
        assert isinstance(result.output, skill.output_model)
        assert skill.output_model.model_validate_json(result.output.model_dump_json()) == result.output


def test_every_first_batch_skill_rejects_permission_and_invalid_arguments() -> None:
    registry = build_default_skill_registry()
    executor = FixtureSkillExecutor(registry)

    for skill_name in EXPECTED_SKILL_NAMES:
        with pytest.raises(SkillPermissionDeniedError):
            asyncio.run(
                executor.execute(
                    skill_name=skill_name,
                    arguments=VALID_ARGUMENTS[skill_name],
                    context=_fixture_context(role_mask=1, scopes=frozenset()),
                )
            )
        with pytest.raises(SkillInvalidArgumentsError):
            asyncio.run(executor.execute(skill_name=skill_name, arguments={}, context=_fixture_context()))


def test_keyed_interaction_skill_is_idempotent_in_fixture_executor() -> None:
    executor = FixtureSkillExecutor(build_default_skill_registry())
    context = _fixture_context()

    first = asyncio.run(executor.execute(skill_name="interaction.ask_admin", arguments=VALID_ARGUMENTS["interaction.ask_admin"], context=context))
    second = asyncio.run(executor.execute(skill_name="interaction.ask_admin", arguments=VALID_ARGUMENTS["interaction.ask_admin"], context=context))

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert first.output == second.output


class RetryInput(DomainModel):
    value: str = Field(min_length=1)


class RetryOutput(DomainModel):
    value: str


class FlakySkill(BaseSkill[RetryInput, RetryOutput]):
    input_model = RetryInput
    output_model = RetryOutput
    spec = SkillSpec(
        name="test.flaky",
        version="1.0",
        description="test retry",
        input_model="RetryInput",
        output_model="RetryOutput",
        side_effect="none",
        permission_scopes=["agentic.admin"],
        timeout_seconds=1.0,
        retry_policy=RetryPolicy(max_attempts=2, retryable_error_codes=["transient"]),
        idempotency=IdempotencyMode.NON_IDEMPOTENT,
        observation_training_role=ObservationTrainingRole.HIDDEN,
        environment_adapter="test",
        cost_model=SkillCost(),
    )

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, context: SkillExecutionContext, payload: RetryInput) -> RetryOutput:
        del context
        self.calls += 1
        if self.calls == 1:
            raise SkillExecutionError("temporary", code="transient", retryable=True)
        return RetryOutput(value=payload.value)


class SlowSkill(BaseSkill[RetryInput, RetryOutput]):
    input_model = RetryInput
    output_model = RetryOutput
    spec = SkillSpec(
        name="test.slow",
        version="1.0",
        description="test timeout",
        input_model="RetryInput",
        output_model="RetryOutput",
        side_effect="none",
        permission_scopes=["agentic.admin"],
        timeout_seconds=0.001,
        retry_policy=RetryPolicy(max_attempts=1),
        idempotency=IdempotencyMode.NON_IDEMPOTENT,
        observation_training_role=ObservationTrainingRole.HIDDEN,
        environment_adapter="test",
        cost_model=SkillCost(),
    )

    async def execute(self, context: SkillExecutionContext, payload: RetryInput) -> RetryOutput:
        del context, payload
        await asyncio.sleep(0.02)
        return RetryOutput(value="late")


def test_live_executor_retries_retryable_failures_and_enforces_timeout() -> None:
    flaky = FlakySkill()
    executor = LiveSkillExecutor(SkillRegistry([flaky, SlowSkill()]))
    context = SkillExecutionContext(
        admin_actor_id=3,
        role_mask=8,
        permission_scopes=frozenset({"agentic.admin"}),
        mode=SkillExecutionMode.LIVE,
    )

    result = asyncio.run(executor.execute(skill_name="test.flaky", arguments={"value": "ok"}, context=context))
    assert result.output == RetryOutput(value="ok")
    assert result.attempts == 2
    with pytest.raises(SkillTimeoutError):
        asyncio.run(executor.execute(skill_name="test.slow", arguments={"value": "late"}, context=context))
