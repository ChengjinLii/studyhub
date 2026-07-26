from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.agentic_platform.domain.artifact import ArtifactRef
from app.agentic_platform.domain.invariants import apply_state_delta
from app.agentic_platform.domain.observation import EvidenceReference
from app.agentic_platform.domain.plan import AgentPlan, PlanStep, PlanStepStatus
from app.agentic_platform.domain.state import AgentBudget, StateDelta, WorkingSet
from tests.agentic_platform.factories import agent_plan, artifact_ref, task_state


def test_domain_models_forbid_extra_fields_and_large_artifact_text() -> None:
    with pytest.raises(ValidationError):
        ArtifactRef(
            artifact_id="artifact-1",
            version=1,
            uri="artifact://agentic/artifact-1/v1",
            unexpected="not allowed",
        )
    with pytest.raises(ValidationError):
        ArtifactRef.model_validate(artifact_ref().model_dump(mode="python") | {"summary": "x" * 1_025})


def test_evidence_page_must_be_positive_and_budget_must_not_be_negative() -> None:
    with pytest.raises(ValidationError, match="greater than 0"):
        EvidenceReference(evidence_id="evidence-1", source_uri="material://1", page=0)
    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        AgentBudget(turns_remaining=-1, skill_calls_remaining=0, context_tokens_remaining=0, cost_remaining=0.0)


def test_plan_rejects_cycles_missing_dependencies_and_duplicate_ids() -> None:
    def step(step_id: str, depends_on: list[str]) -> PlanStep:
        return PlanStep(
            step_id=step_id,
            title=step_id,
            depends_on=depends_on,
            capability="test.capability",
            completion_check="complete",
        )

    base = {
        "plan_id": "plan-cyclic",
        "version": 1,
        "objective": "test",
        "created_by_policy_version": "test-policy-v1",
    }
    with pytest.raises(ValidationError, match="cycle"):
        AgentPlan(**base, steps=[step("a", ["b"]), step("b", ["a"])])
    with pytest.raises(ValidationError, match="unknown dependencies"):
        AgentPlan(**base, steps=[step("a", ["missing"])])
    with pytest.raises(ValidationError, match="unique"):
        AgentPlan(**base, steps=[step("a", []), step("a", [])])


def test_accepted_and_rejected_ids_cannot_conflict() -> None:
    with pytest.raises(ValidationError, match="conflict"):
        WorkingSet(accepted_ids=["candidate-1"], rejected_ids=["candidate-1"])
    with pytest.raises(ValidationError, match="accepted and rejected"):
        StateDelta(accepted_ids_to_add=["candidate-1"], rejected_ids_to_add=["candidate-1"])


def test_apply_state_delta_returns_a_new_valid_state_without_mutating_the_original() -> None:
    original = task_state()
    original_dump = deepcopy(original.model_dump(mode="json"))
    delta = StateDelta(
        resolved_constraint_ids=["constraint-1"],
        completed_milestone_ids=["milestone-1"],
        candidate_ids_to_add=["candidate-1", "candidate-2"],
        accepted_ids_to_add=["candidate-1"],
        evidence_refs_to_add=[artifact_ref("evidence-1")],
        artifact_refs_to_add=[artifact_ref("report-1")],
        plan_step_status_updates={"review": PlanStepStatus.COMPLETED},
        budget_consumption={"turns": 1, "skill_calls": 2, "context_tokens": 300, "cost": 1.5},
        last_transition_id="transition-1",
    )

    successor = apply_state_delta(original, delta)

    assert original.model_dump(mode="json") == original_dump
    assert original is not successor
    assert successor.constraints[0].is_resolved is True
    assert successor.milestones[0].is_completed is True
    assert successor.working_set.candidate_ids == ["candidate-1", "candidate-2"]
    assert successor.working_set.accepted_ids == ["candidate-1"]
    assert [ref.artifact_id for ref in successor.working_set.evidence_refs] == ["evidence-1"]
    assert [ref.artifact_id for ref in successor.active_artifacts] == ["report-1"]
    assert successor.plan.steps[1].status == PlanStepStatus.COMPLETED
    assert successor.budget.turns_remaining == 7
    assert successor.budget.skill_calls_remaining == 10
    assert successor.budget.context_tokens_remaining == 15_700
    assert successor.budget.cost_remaining == 8.5
    assert successor.last_transition_id == "transition-1"


def test_apply_state_delta_rejects_unknown_ids_and_budget_underflow() -> None:
    state = task_state()
    with pytest.raises(ValueError, match="unknown constraint"):
        apply_state_delta(state, StateDelta(resolved_constraint_ids=["missing"]))
    with pytest.raises(ValueError, match="budget negative"):
        apply_state_delta(state, StateDelta(budget_consumption={"turns": 9}))


def test_apply_state_delta_can_replace_a_valid_plan_without_graph_local_mutation() -> None:
    original = task_state()
    revised = agent_plan().model_copy(update={"plan_id": "plan-2", "version": 2})

    successor = apply_state_delta(
        original,
        StateDelta(
            plan_update=revised,
            plan_step_status_updates={"review": PlanStepStatus.IN_PROGRESS},
        ),
    )

    assert original.plan.plan_id == "plan-1"
    assert successor.plan.plan_id == "plan-2"
    assert successor.plan.version == 2
    assert successor.plan.steps[1].status == PlanStepStatus.IN_PROGRESS
