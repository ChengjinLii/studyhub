from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from app.agentic_platform.policy.context_view import ContextPurpose
from app.agentic_platform.policy.model_provider import AgentModelProvider, AgentModelRequest

from .prompts import ResearchPromptPurpose, build_research_policy_view, render_research_prompt
from .state import DeepResearchState, ResearchDecision, ResearchPlan, ResearchReport, ResearchSection, SubQuestion


class ResearchPolicy(Protocol):
    async def create_plan(self, state: DeepResearchState) -> ResearchPlan:
        ...

    async def decide(self, state: DeepResearchState) -> ResearchDecision:
        ...

    async def finalize(self, state: DeepResearchState) -> ResearchReport:
        ...


class ResearchPolicyOutputError(ValueError):
    def __init__(self, *, purpose: ResearchPromptPurpose, schema_name: str, error_types: list[str]) -> None:
        self.purpose = purpose
        self.schema_name = schema_name
        self.error_types = error_types
        super().__init__(f"invalid research policy output for {purpose.value}/{schema_name}: {error_types}")


OutputT = TypeVar("OutputT", bound=BaseModel)


class ModelResearchPolicy:
    """Structured research planner/policy/finalizer backed by the shared provider contract."""

    def __init__(self, provider: AgentModelProvider, *, token_budget: int = 16_000) -> None:
        self.provider = provider
        self.token_budget = token_budget

    async def create_plan(self, state: DeepResearchState) -> ResearchPlan:
        return await self._request(state, ResearchPromptPurpose.PLANNER, ResearchPlan, max_output_tokens=1_500)

    async def decide(self, state: DeepResearchState) -> ResearchDecision:
        return await self._request(state, ResearchPromptPurpose.POLICY, ResearchDecision, max_output_tokens=900)

    async def finalize(self, state: DeepResearchState) -> ResearchReport:
        return await self._request(state, ResearchPromptPurpose.FINALIZER, ResearchReport, max_output_tokens=2_000)

    async def _request(
        self,
        state: DeepResearchState,
        purpose: ResearchPromptPurpose,
        output_model: type[OutputT],
        *,
        max_output_tokens: int,
    ) -> OutputT:
        view = build_research_policy_view(
            state,
            purpose=purpose,
            token_budget=min(self.token_budget, state.budget.remaining_context_tokens),
        )
        prompt = render_research_prompt(view, output_model)
        response = await self.provider.complete(
            AgentModelRequest(
                purpose={
                    ResearchPromptPurpose.PLANNER: ContextPurpose.PLANNER,
                    ResearchPromptPurpose.POLICY: ContextPurpose.POLICY,
                    ResearchPromptPurpose.FINALIZER: ContextPurpose.FINALIZER,
                }[purpose],
                rendered_prompt=prompt.rendered_prompt,
                context_hash=prompt.context_hash,
                prompt_hash=prompt.prompt_hash,
                output_schema_name=output_model.__name__,
                output_schema=output_model.model_json_schema(),
                max_output_tokens=max_output_tokens,
            )
        )
        try:
            return output_model.model_validate(response.structured_output)
        except ValidationError as exc:
            errors = exc.errors(include_url=False, include_input=False)
            raise ResearchPolicyOutputError(
                purpose=purpose,
                schema_name=output_model.__name__,
                error_types=sorted({str(item.get("type") or "validation_error") for item in errors}),
            ) from exc


class ReplayResearchPolicy:
    """Deterministic research policy used by scenario/recovery tests only."""

    def __init__(
        self,
        *,
        plans: Iterable[ResearchPlan] = (),
        decisions: Iterable[ResearchDecision] = (),
        reports: Iterable[ResearchReport] = (),
    ) -> None:
        self._plans = deque(plan.model_copy(deep=True) for plan in plans)
        self._decisions = deque(decision.model_copy(deep=True) for decision in decisions)
        self._reports = deque(report.model_copy(deep=True) for report in reports)

    async def create_plan(self, state: DeepResearchState) -> ResearchPlan:
        if self._plans:
            return self._plans.popleft()
        return ResearchPlan(
            plan_id=f"research-plan-{state.task.task_id}",
            version=1,
            outline=[ResearchSection(section_id="findings", title="Findings", objective=state.research_question)],
            sub_questions=[SubQuestion(question_id="primary", question=state.research_question)],
            rationale_summary="Deterministic replay plan.",
        )

    async def decide(self, state: DeepResearchState) -> ResearchDecision:
        del state
        if not self._decisions:
            raise LookupError("research decision replay script is exhausted")
        return self._decisions.popleft()

    async def finalize(self, state: DeepResearchState) -> ResearchReport:
        if self._reports:
            return self._reports.popleft()
        from .report import build_research_report

        return build_research_report(state)
