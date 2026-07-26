from __future__ import annotations

from app.agentic_platform.domain.artifact import ArtifactKind, ArtifactRef
from app.agentic_platform.domain.decision import AgentActionType, AgentDecision, ExpectedStateChange
from app.agentic_platform.domain.plan import AgentPlan, PlanStep, PlanStepStatus
from app.agentic_platform.domain.reward_facts import RewardFacts
from app.agentic_platform.domain.state import (
    AgentBudget,
    AgentTaskState,
    ConstraintState,
    EnvironmentRef,
    GoalState,
    MilestoneState,
    StateDelta,
    TriggerContext,
    TriggerType,
)
from app.agentic_platform.domain.transition import AgentTransitionEvent, ModelUsage, VerifierResult


def artifact_ref(
    artifact_id: str = "artifact-1",
    *,
    version: int = 1,
    artifact_type: ArtifactKind | str = ArtifactKind.OBSERVATION,
) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=artifact_id,
        artifact_type=artifact_type,
        version=version,
        uri=f"artifact://agentic/{artifact_id}/v{version}",
        content_hash=f"sha256-{artifact_id}-{version}",
        summary="bounded test artifact",
    )


def agent_plan() -> AgentPlan:
    return AgentPlan(
        plan_id="plan-1",
        version=1,
        objective="Create an evidence-grounded study plan",
        success_criteria=["All milestones are reviewed"],
        created_by_policy_version="test-policy-v1",
        steps=[
            PlanStep(
                step_id="gather",
                title="Gather material evidence",
                capability="research.search_internal",
                completion_check="At least one source is recorded",
            ),
            PlanStep(
                step_id="review",
                title="Review the proposed plan",
                depends_on=["gather"],
                capability="plan.review",
                completion_check="The review passes",
            ),
        ],
    )


def task_state() -> AgentTaskState:
    return AgentTaskState(
        thread_id="thread-1",
        run_id="run-1",
        user_id=7,
        admin_actor_id=3,
        trigger=TriggerContext(trigger_type=TriggerType.ADMIN_API, source="admin-console", request_id="request-1"),
        goal=GoalState(goal_id="goal-1", statement="Produce an admin-only study recommendation"),
        constraints=[ConstraintState(constraint_id="constraint-1", description="Use only verified material")],
        milestones=[MilestoneState(milestone_id="milestone-1", description="Research reviewed")],
        plan=agent_plan(),
        environment=EnvironmentRef(snapshot_id="snapshot-1", snapshot_hash="snapshot-hash-1", source="fixture"),
        budget=AgentBudget(
            turns_remaining=8,
            skill_calls_remaining=12,
            context_tokens_remaining=16_000,
            cost_remaining=10.0,
            subagent_turns_remaining=4,
        ),
    )


def decision() -> AgentDecision:
    return AgentDecision(
        action_type=AgentActionType.REVIEW,
        plan_step_id="review",
        rationale_summary="Review the collected evidence against the plan criteria.",
        expected_state_change=ExpectedStateChange(summary="The review result will be recorded."),
    )


def transition(*, exported_at=None) -> AgentTransitionEvent:
    return AgentTransitionEvent(
        thread_id="thread-1",
        run_id="run-1",
        transition_id="transition-1",
        parent_transition_id=None,
        turn_index=0,
        plan_step_id="review",
        environment_snapshot_id="snapshot-1",
        state_before_hash="before-hash",
        state_after_hash="after-hash",
        state_abstract_key="state-key",
        policy_version="test-policy-v1",
        model_id="test-model",
        prompt_template_hash="prompt-hash",
        skill_catalog_hash="catalog-hash",
        action_schema_hash="action-schema-hash",
        context_view_ref=artifact_ref("context", artifact_type=ArtifactKind.CONTEXT_VIEW),
        parsed_decision=decision(),
        state_delta=StateDelta(),
        verifier_result=VerifierResult(passed=True, summary="All checks passed."),
        reward_facts=RewardFacts(),
        usage=ModelUsage(total_tokens=0),
        exported_at=exported_at,
    )


def completed_plan_step_status() -> PlanStepStatus:
    return PlanStepStatus.COMPLETED
