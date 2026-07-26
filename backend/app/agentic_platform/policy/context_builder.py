from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from app.agentic_platform.domain.artifact import ArtifactRef
from app.agentic_platform.domain.hashing import canonical_hash, canonical_json
from app.agentic_platform.domain.state import AgentTaskState
from app.agentic_platform.skills.base import BaseSkill

from .context_view import (
    ContextArtifactRef,
    ContextBudget,
    ContextCapability,
    ContextConstraint,
    ContextMilestone,
    ContextPlanStep,
    ContextPurpose,
    ContextView,
    ContextWorkingSet,
)


_SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(?:[a-z0-9_-]*?(?:api[_-]?key|access[_-]?token|token|secret|password|authorization|cookie|credential))\b\s*[:=]\s*[^\s,;]+"
)


class ContextBuilder:
    """Creates purpose-specific, token-bounded views without raw tool payloads."""

    def __init__(self, *, token_budget: int) -> None:
        if token_budget <= 0:
            raise ValueError("token_budget must be positive")
        self.token_budget = token_budget

    def build_planner_context(self, state: AgentTaskState, skills: Iterable[BaseSkill]) -> ContextView:
        return self._build(
            state,
            purpose=ContextPurpose.PLANNER,
            capabilities=self._capabilities(skills),
            observation_summaries=[],
            include_working_set=False,
            include_active_artifacts=False,
        )

    def build_policy_context(
        self,
        state: AgentTaskState,
        skills: Iterable[BaseSkill],
        *,
        observation_summaries: Iterable[str] = (),
    ) -> ContextView:
        return self._build(
            state,
            purpose=ContextPurpose.POLICY,
            capabilities=self._capabilities(skills),
            observation_summaries=[self._redact_text(item, max_length=1_000) for item in observation_summaries],
            include_working_set=True,
            include_active_artifacts=True,
        )

    def build_final_context(self, state: AgentTaskState) -> ContextView:
        return self._build(
            state,
            purpose=ContextPurpose.FINALIZER,
            capabilities=[],
            observation_summaries=[],
            include_working_set=True,
            include_active_artifacts=True,
        )

    def _build(
        self,
        state: AgentTaskState,
        *,
        purpose: ContextPurpose,
        capabilities: list[ContextCapability],
        observation_summaries: list[str],
        include_working_set: bool,
        include_active_artifacts: bool,
    ) -> ContextView:
        working_set = ContextWorkingSet()
        if include_working_set:
            working_set = ContextWorkingSet(
                candidate_ids=list(state.working_set.candidate_ids),
                accepted_ids=list(state.working_set.accepted_ids),
                rejected_ids=list(state.working_set.rejected_ids),
                evidence_artifacts=[self._artifact_ref(ref) for ref in state.working_set.evidence_refs],
            )
        view = ContextView(
            purpose=purpose,
            thread_id=state.thread_id,
            run_id=state.run_id,
            goal=self._redact_text(state.goal.statement, max_length=2_000),
            success_criteria=[self._redact_text(item, max_length=500) for item in state.goal.success_criteria],
            constraints=[
                ContextConstraint(
                    constraint_id=item.constraint_id,
                    description=self._redact_text(item.description, max_length=1_000),
                    is_resolved=item.is_resolved,
                )
                for item in state.constraints
            ],
            milestones=[
                ContextMilestone(
                    milestone_id=item.milestone_id,
                    description=self._redact_text(item.description, max_length=1_000),
                    is_completed=item.is_completed,
                )
                for item in state.milestones
            ],
            plan_id=state.plan.plan_id,
            plan_version=state.plan.version,
            plan_steps=[
                ContextPlanStep(
                    step_id=item.step_id,
                    title=self._redact_text(item.title, max_length=512),
                    status=item.status,
                    depends_on=list(item.depends_on),
                    capability=item.capability,
                    completion_check=self._redact_text(item.completion_check, max_length=1_000),
                )
                for item in state.plan.steps
            ],
            capabilities=capabilities,
            capability_catalog_hash=canonical_hash(
                [
                    {
                        "name": capability.name,
                        "version": capability.version,
                        "input_model": capability.input_model,
                        "output_model": capability.output_model,
                    }
                    for capability in capabilities
                ]
            ),
            capability_count=len(capabilities),
            working_set=working_set,
            active_artifacts=[self._artifact_ref(ref) for ref in state.active_artifacts] if include_active_artifacts else [],
            observation_summaries=[item for item in observation_summaries if item],
            budget=ContextBudget(
                turns_remaining=state.budget.turns_remaining,
                skill_calls_remaining=state.budget.skill_calls_remaining,
                context_tokens_remaining=state.budget.context_tokens_remaining,
                cost_remaining=state.budget.cost_remaining,
            ),
            terminal_status=state.terminal.status.value if state.terminal is not None else None,
            token_budget=self.token_budget,
            estimated_tokens=0,
        )
        return self._fit_to_budget(view)

    @staticmethod
    def _artifact_ref(reference: ArtifactRef) -> ContextArtifactRef:
        return ContextArtifactRef(
            artifact_id=reference.artifact_id,
            artifact_type=str(reference.artifact_type),
            version=reference.version,
            summary=ContextBuilder._redact_text(reference.summary, max_length=512) if reference.summary else None,
        )

    @staticmethod
    def _capabilities(skills: Iterable[BaseSkill]) -> list[ContextCapability]:
        return [
            ContextCapability(
                name=skill.spec.name,
                version=skill.spec.version,
                description=ContextBuilder._redact_text(skill.spec.description, max_length=1_000),
                side_effect=skill.spec.side_effect,
                requires_approval=skill.spec.requires_approval,
                input_model=skill.spec.input_model,
                output_model=skill.spec.output_model,
            )
            for skill in skills
        ]

    def _fit_to_budget(self, view: ContextView) -> ContextView:
        data = view.model_dump(mode="python")
        truncated = False
        while self._estimate_tokens(data) > self.token_budget:
            truncated = True
            if data["observation_summaries"]:
                data["observation_summaries"].pop()
                continue
            if data["active_artifacts"]:
                data["active_artifacts"].pop()
                continue
            if data["working_set"]["evidence_artifacts"]:
                data["working_set"]["evidence_artifacts"].pop()
                continue
            if data["plan_steps"]:
                data["plan_steps"].pop()
                continue
            if data["milestones"]:
                data["milestones"].pop()
                continue
            if data["constraints"]:
                data["constraints"].pop()
                continue
            if data["success_criteria"]:
                data["success_criteria"].pop()
                continue
            if not self._shorten_longest_text(data):
                break
        data["estimated_tokens"] = self._estimate_tokens(data)
        data["truncated"] = truncated
        if data["estimated_tokens"] > self.token_budget:
            raise ValueError("context cannot fit within its token budget")
        return ContextView.model_validate(data)

    @staticmethod
    def _estimate_tokens(data: dict[str, Any]) -> int:
        stable_data = dict(data)
        stable_data.pop("estimated_tokens", None)
        stable_data.pop("truncated", None)
        return max(1, (len(canonical_json(stable_data)) + 3) // 4)

    @classmethod
    def _shorten_longest_text(cls, value: Any) -> bool:
        candidates: list[tuple[int, dict[str, Any], str]] = []

        def visit(item: Any) -> None:
            if isinstance(item, dict):
                for key, child in item.items():
                    if key in {"thread_id", "run_id", "plan_id", "schema_version"}:
                        continue
                    if isinstance(child, str) and len(child) > 16:
                        candidates.append((len(child), item, key))
                    else:
                        visit(child)
            elif isinstance(item, list):
                for child in item:
                    visit(child)

        visit(value)
        if not candidates:
            return False
        _length, parent, key = max(candidates, key=lambda item: item[0])
        original = parent[key]
        parent[key] = f"{original[: max(8, len(original) // 2 - 1)]}…"
        return True

    @staticmethod
    def _redact_text(value: object, *, max_length: int) -> str:
        normalized = " ".join(str(value or "").split()).strip()
        sanitized = _SECRET_ASSIGNMENT_PATTERN.sub("[redacted]", normalized)
        return sanitized[:max_length] or "[empty]"
