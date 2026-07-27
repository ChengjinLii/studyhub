from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from app.agentic_platform.domain.artifact import ArtifactKind, ArtifactRef
from app.agentic_platform.domain.hashing import canonical_hash
from app.agentic_platform.policy.context_view import ContextPurpose
from app.agentic_platform.policy.model_provider import AgentModelProvider, AgentModelRequest
from app.agentic_platform.policy.token_trace import TokenTrace
from app.agentic_platform.policy.turn_result import PolicyTurnResult

from .prompts import ResearchPromptPurpose, build_research_policy_view, render_research_prompt
from .state import DeepResearchState, ResearchDecision, ResearchPlan, ResearchReport, ResearchSection, SubQuestion
from .transition import InMemoryResearchArtifactStore, ResearchArtifactStore


class ResearchPolicy(Protocol):
    async def create_plan(self, state: DeepResearchState) -> PolicyTurnResult[ResearchPlan]:
        ...

    async def decide(self, state: DeepResearchState) -> PolicyTurnResult[ResearchDecision]:
        ...

    async def finalize(self, state: DeepResearchState) -> PolicyTurnResult[ResearchReport]:
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

    def __init__(
        self,
        provider: AgentModelProvider,
        *,
        token_budget: int = 16_000,
        raw_output_store: ResearchArtifactStore | None = None,
    ) -> None:
        self.provider = provider
        self.token_budget = token_budget
        self.raw_output_store = raw_output_store or InMemoryResearchArtifactStore()

    async def create_plan(self, state: DeepResearchState) -> PolicyTurnResult[ResearchPlan]:
        return await self._request(state, ResearchPromptPurpose.PLANNER, ResearchPlan, max_output_tokens=1_500)

    async def decide(self, state: DeepResearchState) -> PolicyTurnResult[ResearchDecision]:
        return await self._request(state, ResearchPromptPurpose.POLICY, ResearchDecision, max_output_tokens=900)

    async def finalize(self, state: DeepResearchState) -> PolicyTurnResult[ResearchReport]:
        return await self._request(state, ResearchPromptPurpose.FINALIZER, ResearchReport, max_output_tokens=2_000)

    async def _request(
        self,
        state: DeepResearchState,
        purpose: ResearchPromptPurpose,
        output_model: type[OutputT],
        *,
        max_output_tokens: int,
    ) -> PolicyTurnResult[OutputT]:
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
        raw_ref = await self._store_raw_output(
            state=state,
            purpose=purpose,
            model_id=response.model_id,
            prompt_hash=prompt.prompt_hash,
            raw_content=response.raw_content,
        )
        try:
            parsed = output_model.model_validate(response.structured_output)
        except ValidationError as exc:
            errors = exc.errors(include_url=False, include_input=False)
            raise ResearchPolicyOutputError(
                purpose=purpose,
                schema_name=output_model.__name__,
                error_types=sorted({str(item.get("type") or "validation_error") for item in errors}),
            ) from exc
        trace = TokenTrace(
            source=response.token_trace_source,
            token_ids=response.token_ids,
            token_logprobs=response.token_logprobs,
            token_role_spans=response.token_role_spans,
        )
        return PolicyTurnResult(
            parsed_output=parsed,
            model_id=response.model_id,
            model_revision=response.model_revision,
            prompt_hash=prompt.prompt_hash,
            context_hash=prompt.context_hash,
            raw_model_output_ref=raw_ref,
            token_ids=trace.token_ids,
            token_logprobs=trace.token_logprobs,
            token_role_spans=trace.token_role_spans,
            usage=response.usage,
            latency_ms=response.latency_ms,
            finish_reason=response.finish_reason,
            provider_request_id=response.provider_request_id,
            token_trace_source=trace.source,
            trainable=trace.trainable,
        )

    async def _store_raw_output(
        self,
        *,
        state: DeepResearchState,
        purpose: ResearchPromptPurpose,
        model_id: str,
        prompt_hash: str,
        raw_content: str | None,
    ) -> ArtifactRef | None:
        if raw_content is None:
            return None
        return await self.raw_output_store.store_json(
            state,
            artifact_type=ArtifactKind.RAW_MODEL_OUTPUT,
            artifact_key=f"research-raw-model-{purpose.value}",
            payload={
                "schema_version": "1.0",
                "purpose": purpose.value,
                "model_id": model_id,
                "prompt_hash": prompt_hash,
                "raw_content": raw_content,
            },
            summary=f"Restricted DeepResearch {purpose.value} model output",
            idempotency_key=f"research-raw-model:{purpose.value}:{prompt_hash}",
        )


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

    async def create_plan(self, state: DeepResearchState) -> PolicyTurnResult[ResearchPlan]:
        if self._plans:
            plan = self._plans.popleft()
        else:
            plan = ResearchPlan(
                plan_id=f"research-plan-{state.task.task_id}",
                version=1,
                outline=[ResearchSection(section_id="findings", title="Findings", objective=state.research_question)],
                sub_questions=[SubQuestion(question_id="primary", question=state.research_question)],
                rationale_summary="Deterministic replay plan.",
            )
        return self._replay_turn(
            plan,
            state=state,
            purpose=ResearchPromptPurpose.PLANNER,
        )

    async def decide(self, state: DeepResearchState) -> PolicyTurnResult[ResearchDecision]:
        if not self._decisions:
            raise LookupError("research decision replay script is exhausted")
        return self._replay_turn(
            self._decisions.popleft(),
            state=state,
            purpose=ResearchPromptPurpose.POLICY,
        )

    async def finalize(self, state: DeepResearchState) -> PolicyTurnResult[ResearchReport]:
        if self._reports:
            report = self._reports.popleft()
        else:
            from .report import build_research_report

            report = build_research_report(state)
        return self._replay_turn(report, state=state, purpose=ResearchPromptPurpose.FINALIZER)

    @staticmethod
    def _replay_turn(output: OutputT, *, state: DeepResearchState, purpose: ResearchPromptPurpose) -> PolicyTurnResult[OutputT]:
        context_hash = canonical_hash(
            {
                "task_id": state.task.task_id,
                "purpose": purpose.value,
                "state": state,
            }
        )
        return PolicyTurnResult(
            parsed_output=output,
            model_id="replay",
            model_revision=None,
            prompt_hash=canonical_hash({"provider": "replay", "purpose": purpose.value, "context_hash": context_hash}),
            context_hash=context_hash,
            trainable=False,
        )
