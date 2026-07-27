from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, StateGraph
from langgraph.types import Command
from pydantic import Field

from app.agentic_platform.domain import DomainModel
from app.agentic_platform.domain.artifact import ArtifactKind, ArtifactRef
from app.agentic_platform.domain.hashing import canonical_hash
from app.agentic_platform.domain.reward_facts import RewardFacts
from app.agentic_platform.domain.transition import ModelTurnPurpose
from app.agentic_platform.policy.turn_result import PolicyTurnResult

from .citation import CitationVerifier
from .domain_router import ResearchDomainRouter
from .policy import ResearchPolicy
from .prompts import ResearchPromptPurpose, build_research_policy_view
from .report import build_research_packet, build_research_report
from .state import (
    DeepResearchState,
    ResearchActionType,
    ResearchBudgetConsumption,
    ResearchDecision,
    ResearchPacket,
    ResearchReport,
    ResearchSourceType,
    ResearchStateDelta,
    ResearchTaskPacket,
    apply_research_delta,
    initial_research_state,
)
from .transition import (
    DeepResearchChildTransition,
    InMemoryResearchArtifactStore,
    InMemoryResearchChildTransitionSink,
    ResearchArtifactStore,
    ResearchChildTransitionSink,
    ResearchModelTurn,
    ResearchRuntimeMetadata,
    ResearchToolObservation,
)


class ResearchGraphState(TypedDict, total=False):
    """Scheduler state only; ``research_state`` remains the domain authority."""

    research_state: dict[str, Any]
    decision: dict[str, Any]
    trace: list[dict[str, Any]]
    report: dict[str, Any]
    terminal_reason: str
    graph_thread_id: str
    child_transition_sequence: int
    previous_child_transition_id: str | None
    planner_turn_result: dict[str, Any]
    policy_turn_result: dict[str, Any]
    finalizer_turn_result: dict[str, Any]


class ResearchTraceEntry(DomainModel):
    schema_version: str = "1.0"
    node_name: str = Field(min_length=1, max_length=128)
    turn_index: int = Field(ge=0)
    action_type: ResearchActionType | None = None
    rationale_summary: str | None = Field(default=None, max_length=2_000)
    summary: str = Field(min_length=1, max_length=2_000)
    state_before_hash: str = Field(min_length=1, max_length=128)
    state_after_hash: str = Field(min_length=1, max_length=128)
    error_code: str | None = Field(default=None, max_length=128)
    child_transition_id: str | None = Field(default=None, max_length=128)


class ResearchTraceStore(Protocol):
    async def store(self, state: DeepResearchState, entries: list[ResearchTraceEntry]) -> ArtifactRef:
        ...


class InMemoryResearchTraceStore:
    """Artifact-first test adapter; a production adapter can persist the same payload."""

    def __init__(self) -> None:
        self.payloads: dict[str, list[dict[str, Any]]] = {}

    async def store(self, state: DeepResearchState, entries: list[ResearchTraceEntry]) -> ArtifactRef:
        payload = [entry.model_dump(mode="json") for entry in entries]
        content_hash = canonical_hash(payload)
        artifact_id = f"research_trace_{content_hash[:24]}"
        self.payloads[artifact_id] = payload
        return ArtifactRef(
            artifact_id=artifact_id,
            artifact_type=ArtifactKind.OTHER,
            version=1,
            uri=f"artifact://agentic/research-traces/{artifact_id}",
            content_hash=content_hash,
            media_type="application/json",
            summary=f"Structured DeepResearch trace for task {state.task.task_id}",
        )


class DeepResearchRunResult(DomainModel):
    schema_version: str = "1.0"
    task_id: str = Field(min_length=1, max_length=128)
    graph_thread_id: str = Field(min_length=1, max_length=256)
    state: DeepResearchState
    report: ResearchReport
    packet: ResearchPacket
    terminal_reason: str = Field(min_length=1, max_length=2_000)
    child_transition_count: int = Field(default=0, ge=0)


class DeepResearchGraph:
    """A policy-directed Search-R1-style research subgraph.

    The graph provides only durable structural stages (plan, decide, execute,
    finalize).  It does not prescribe a search/read/report sequence: the
    research Policy selects each atomic action and may revisit any capability
    while the task's explicit budget still permits it.
    """

    def __init__(
        self,
        *,
        policy: ResearchPolicy,
        router: ResearchDomainRouter,
        checkpointer: Any | None = None,
        trace_store: ResearchTraceStore | None = None,
        artifact_store: ResearchArtifactStore | None = None,
        transition_sink: ResearchChildTransitionSink | None = None,
        trainable_turn_purposes: set[ModelTurnPurpose] | None = None,
        metadata: ResearchRuntimeMetadata | None = None,
    ) -> None:
        self.policy = policy
        self.router = router
        self.trace_store = trace_store or InMemoryResearchTraceStore()
        self.artifact_store = artifact_store or InMemoryResearchArtifactStore()
        self.transition_sink = transition_sink or InMemoryResearchChildTransitionSink()
        self.metadata = metadata or ResearchRuntimeMetadata()
        self.trainable_turn_purposes = trainable_turn_purposes or {
            ModelTurnPurpose.RESEARCH_POLICY,
            ModelTurnPurpose.RESEARCH_FINALIZER,
        }
        self.graph = self._build_graph(checkpointer or InMemorySaver())

    async def run(self, task: ResearchTaskPacket, *, graph_thread_id: str | None = None) -> DeepResearchRunResult:
        thread_id = graph_thread_id or self._graph_thread_id(task.task_id)
        config = {
            "recursion_limit": self._recursion_limit(task),
            "configurable": {"thread_id": thread_id},
        }
        await self.graph.ainvoke(
            {
                "research_state": initial_research_state(task).model_dump(mode="json"),
                "trace": [],
                "graph_thread_id": thread_id,
                "child_transition_sequence": 0,
                "previous_child_transition_id": None,
            },
            config=config,
        )
        snapshot = await self.graph.aget_state(config)
        if not snapshot.values or "research_state" not in snapshot.values:
            raise RuntimeError("deep research graph produced no state")
        state = DeepResearchState.model_validate(snapshot.values["research_state"])
        report = ResearchReport.model_validate(snapshot.values.get("report") or build_research_report(state))
        packet = build_research_packet(
            state,
            trace_ref=await self._store_trace(state, snapshot.values.get("trace", [])),
        )
        return DeepResearchRunResult(
            task_id=task.task_id,
            graph_thread_id=thread_id,
            state=state,
            report=report,
            packet=packet,
            terminal_reason=str(snapshot.values.get("terminal_reason") or state.terminal_reason or "finalized"),
            child_transition_count=int(snapshot.values.get("child_transition_sequence", 0)),
        )

    def _build_graph(self, checkpointer: Any):
        graph = StateGraph(ResearchGraphState)
        graph.add_node("bootstrap", self._bootstrap)
        graph.add_node("planner", self._planner)
        graph.add_node("policy", self._policy)
        graph.add_node("executor", self._executor)
        graph.add_node("finalizer", self._finalizer)
        graph.add_edge(START, "bootstrap")
        return graph.compile(checkpointer=checkpointer, name="studyhub-deep-research-v1")

    async def _bootstrap(self, graph_state: Mapping[str, Any]) -> Command:
        state = self._load_state(graph_state)
        return Command(update={"research_state": self._dump_state(state)}, goto="planner")

    async def _planner(self, graph_state: Mapping[str, Any]) -> Command:
        state_before = self._load_state(graph_state)
        if state_before.budget.remaining_turns <= 0 or state_before.budget.remaining_context_tokens <= 0:
            return self._to_finalizer(graph_state, state_before, "research_budget_exhausted_before_planning")
        try:
            context = self._context_view(state_before, ResearchPromptPurpose.PLANNER)
            context_tokens = self._context_tokens(context)
            context_ref = await self._store_context_view(state_before, context=context, graph_state=graph_state)
            planner_turn = self._coerce_policy_turn(
                await self.policy.create_plan(state_before),
                state=state_before,
                context=context,
                purpose=ResearchPromptPurpose.PLANNER,
            )
            plan = planner_turn.parsed_output
            delta = ResearchStateDelta(
                plan=planner_turn.parsed_output,
                budget_consumption=ResearchBudgetConsumption(turns=1, context_tokens=context_tokens),
            )
            state_after = apply_research_delta(state_before, delta)
            summary = f"Research plan {plan.plan_id} version {plan.version} is available for policy selection."
            update = await self._state_update(
                graph_state,
                state_before,
                state_after,
                node_name="planner",
                summary=summary,
                state_delta=delta,
                context_view_ref=context_ref,
                model_turn=self._model_turn(planner_turn, ModelTurnPurpose.RESEARCH_PLANNER),
            )
            update["planner_turn_result"] = planner_turn.runtime_metadata()
            return Command(update=update, goto="policy")
        except Exception as exc:  # noqa: BLE001 - adapter/model detail is intentionally not emitted.
            return self._to_finalizer(graph_state, state_before, f"research_planner_failed:{exc.__class__.__name__}")

    async def _policy(self, graph_state: Mapping[str, Any]) -> Command:
        state_before = self._load_state(graph_state)
        if state_before.budget.remaining_turns <= 0 or state_before.budget.remaining_context_tokens <= 0:
            return self._to_finalizer(graph_state, state_before, "research_budget_exhausted")
        try:
            context = self._context_view(state_before, ResearchPromptPurpose.POLICY)
            context_tokens = self._context_tokens(context)
            context_ref = await self._store_context_view(state_before, context=context, graph_state=graph_state)
            policy_turn = self._coerce_policy_turn(
                await self.policy.decide(state_before),
                state=state_before,
                context=context,
                purpose=ResearchPromptPurpose.POLICY,
            )
            decision = policy_turn.parsed_output
            delta = ResearchStateDelta(budget_consumption=ResearchBudgetConsumption(turns=1, context_tokens=context_tokens))
            state_after = apply_research_delta(state_before, delta)
        except Exception as exc:  # noqa: BLE001
            return self._to_finalizer(graph_state, state_before, f"research_policy_failed:{exc.__class__.__name__}")

        update = await self._state_update(
            graph_state,
            state_before,
            state_after,
            node_name="policy",
            action=decision,
            summary="Policy selected an atomic research action.",
            state_delta=delta,
            context_view_ref=context_ref,
            model_turn=self._model_turn(policy_turn, ModelTurnPurpose.RESEARCH_POLICY),
        )
        update["decision"] = decision.model_dump(mode="json")
        update["policy_turn_result"] = policy_turn.runtime_metadata()
        if decision.action_type == ResearchActionType.PLAN:
            return Command(update=update, goto="planner")
        if decision.action_type in {ResearchActionType.FINALIZE, ResearchActionType.ABORT}:
            update["terminal_reason"] = (
                "policy_abort" if decision.action_type == ResearchActionType.ABORT else "policy_finalize"
            )
            return Command(update=update, goto="finalizer")
        return Command(update=update, goto="executor")

    async def _executor(self, graph_state: Mapping[str, Any]) -> Command:
        state_before = self._load_state(graph_state)
        decision = ResearchDecision.model_validate(graph_state["decision"])
        result = await self.router.execute(state_before, decision)
        state_after = apply_research_delta(state_before, result.delta)
        return Command(
            update=await self._state_update(
                graph_state,
                state_before,
                state_after,
                node_name="executor",
                action=decision,
                summary=result.summary,
                state_delta=result.delta,
                error_code=result.error_code,
            ),
            goto="policy",
        )

    async def _finalizer(self, graph_state: Mapping[str, Any]) -> Command:
        state_before = self._load_state(graph_state)
        reason = str(graph_state.get("terminal_reason") or "finalized")
        report: ResearchReport
        state_after = state_before
        finalizer_turn: PolicyTurnResult[ResearchReport] | None = None
        finalizer_context_ref: ArtifactRef | None = None
        finalizer_budget = ResearchBudgetConsumption()
        if reason != "policy_abort" and state_before.budget.remaining_turns > 0 and state_before.budget.remaining_context_tokens > 0:
            try:
                context = self._context_view(state_before, ResearchPromptPurpose.FINALIZER)
                context_tokens = self._context_tokens(context)
                finalizer_context_ref = await self._store_context_view(
                    state_before,
                    context=context,
                    graph_state=graph_state,
                )
                finalizer_turn = self._coerce_policy_turn(
                    await self.policy.finalize(state_before),
                    state=state_before,
                    context=context,
                    purpose=ResearchPromptPurpose.FINALIZER,
                )
                report = finalizer_turn.parsed_output
                finalizer_budget = ResearchBudgetConsumption(turns=1, context_tokens=context_tokens)
                state_after = apply_research_delta(
                    state_before,
                    ResearchStateDelta(report=report, budget_consumption=finalizer_budget),
                )
            except Exception:  # noqa: BLE001 - deterministic report is a safe recovery artifact.
                report = state_before.report or build_research_report(state_before)
        else:
            report = state_before.report or build_research_report(state_before)
        validation = CitationVerifier().validate(
            report,
            claims=list(state_after.claims),
            evidence=list(state_after.evidence_ledger),
        )
        final_delta = ResearchStateDelta(
            report=report,
            citation_validation=validation,
            terminal_reason=reason,
            budget_consumption=finalizer_budget,
        )
        state_after = apply_research_delta(
            state_before,
            final_delta,
        )
        update = await self._state_update(
            graph_state,
            state_before,
            state_after,
            node_name="finalizer",
            action=self._optional_decision(graph_state),
            summary=validation.summary,
            state_delta=final_delta,
            context_view_ref=finalizer_context_ref,
            model_turn=(
                self._model_turn(finalizer_turn, ModelTurnPurpose.RESEARCH_FINALIZER)
                if finalizer_turn is not None
                else None
            ),
        )
        update.update(
            {
                "report": report.model_dump(mode="json"),
                "terminal_reason": reason,
            }
        )
        if finalizer_turn is not None:
            update["finalizer_turn_result"] = finalizer_turn.runtime_metadata()
        return Command(update=update, goto="__end__")

    def _to_finalizer(
        self,
        graph_state: Mapping[str, Any],
        state: DeepResearchState,
        reason: str,
    ) -> Command:
        return Command(
            update={
                "research_state": self._dump_state(state),
                "terminal_reason": reason,
            },
            goto="finalizer",
        )

    async def _state_update(
        self,
        graph_state: Mapping[str, Any],
        state_before: DeepResearchState,
        state_after: DeepResearchState,
        *,
        node_name: str,
        summary: str,
        state_delta: ResearchStateDelta,
        action: ResearchDecision | None = None,
        error_code: str | None = None,
        context_view_ref: ArtifactRef | None = None,
        model_turn: ResearchModelTurn | None = None,
    ) -> dict[str, Any]:
        sequence = int(graph_state.get("child_transition_sequence", 0))
        state_before_hash = canonical_hash(state_before)
        state_after_hash = canonical_hash(state_after)
        child_transition_id = "research_child_" + canonical_hash(
            {
                "task_id": state_before.task.task_id,
                "parent_transition_id": state_before.task.parent_transition_id,
                "sequence": sequence,
                "node": node_name,
                "state_before_hash": state_before_hash,
                "state_after_hash": state_after_hash,
                "action": action,
            }
        )[:40]
        observation = self._tool_observation(state_before, state_after, action, error_code=error_code)
        observation_ref = None
        if observation is not None:
            observation_ref = await self.artifact_store.store_json(
                state_before,
                artifact_type=ArtifactKind.OBSERVATION,
                artifact_key=f"research-tool-observation-{action.action_type.value}",
                payload=observation.model_dump(mode="json"),
                summary=f"Sanitized {action.action_type.value} tool observation",
                idempotency_key=f"research-observation:{child_transition_id}",
            )
        reward_facts = self._reward_facts(
            state_before,
            state_after,
            action=action,
            state_delta=state_delta,
            model_turn=model_turn,
        )
        child_event = DeepResearchChildTransition(
            child_transition_id=child_transition_id,
            parent_transition_id=state_before.task.parent_transition_id,
            previous_child_transition_id=graph_state.get("previous_child_transition_id"),
            sequence_in_subagent=sequence,
            task_id=state_before.task.task_id,
            graph_thread_id=str(graph_state.get("graph_thread_id") or self._graph_thread_id(state_before.task.task_id)),
            node_name=node_name,
            policy_version=self.metadata.policy_version,
            skill_catalog_hash=self.metadata.skill_catalog_hash,
            retriever_version=self.metadata.retriever_version,
            environment_snapshot_id=self.metadata.environment_snapshot_id,
            environment_snapshot_hash=self.metadata.environment_snapshot_hash,
            state_before_hash=state_before_hash,
            state_after_hash=state_after_hash,
            parsed_decision=action,
            state_delta=state_delta,
            context_view_ref=context_view_ref,
            observation_ref=observation_ref,
            observation=observation,
            model_turn=model_turn,
            reward_facts=reward_facts,
            data_policy=self.metadata.data_policy.model_copy(deep=True),
            error_code=error_code,
            summary=summary,
        )
        await self.transition_sink.emit(child_event)
        entry = ResearchTraceEntry(
            node_name=node_name,
            turn_index=len(graph_state.get("trace", [])),
            action_type=action.action_type if action else None,
            rationale_summary=action.rationale_summary if action else None,
            summary=summary,
            state_before_hash=state_before_hash,
            state_after_hash=state_after_hash,
            error_code=error_code,
            child_transition_id=child_transition_id,
        )
        return {
            "research_state": self._dump_state(state_after),
            "trace": [*graph_state.get("trace", []), entry.model_dump(mode="json")],
            "child_transition_sequence": sequence + 1,
            "previous_child_transition_id": child_transition_id,
        }

    @staticmethod
    def _tool_observation(
        state_before: DeepResearchState,
        state_after: DeepResearchState,
        action: ResearchDecision | None,
        *,
        error_code: str | None,
    ) -> ResearchToolObservation | None:
        if action is None or action.action_type not in {
            ResearchActionType.SEARCH_INTERNAL,
            ResearchActionType.SEARCH_WEB,
            ResearchActionType.SEARCH_SCHOLAR,
            ResearchActionType.READ_INTERNAL,
            ResearchActionType.READ_WEB,
        }:
            return None
        source_ids_before = {item.source_id for item in state_before.visited_sources}
        evidence_ids_before = {item.evidence_id for item in state_before.evidence_ledger}
        sources = [item for item in state_after.visited_sources if item.source_id not in source_ids_before]
        evidence = [item for item in state_after.evidence_ledger if item.evidence_id not in evidence_ids_before]
        source_types = list(dict.fromkeys([item.source_type for item in sources] + [item.source_type for item in evidence]))
        if not source_types:
            source_types = {
                ResearchActionType.SEARCH_INTERNAL: [ResearchSourceType.INTERNAL_MATERIAL],
                ResearchActionType.SEARCH_WEB: [ResearchSourceType.WEB],
                ResearchActionType.SEARCH_SCHOLAR: [ResearchSourceType.SCHOLAR],
                ResearchActionType.READ_INTERNAL: [ResearchSourceType.INTERNAL_PDF],
                ResearchActionType.READ_WEB: [ResearchSourceType.WEB],
            }[action.action_type]
        return ResearchToolObservation(
            action_type=action.action_type,
            query=action.query or state_before.research_question,
            source_types=source_types,
            result_count=len(sources),
            evidence_count=len(evidence),
            source_ids=[item.source_id for item in sources],
            evidence_ids=[item.evidence_id for item in evidence],
            error_code=error_code,
        )

    @staticmethod
    def _reward_facts(
        state_before: DeepResearchState,
        state_after: DeepResearchState,
        *,
        action: ResearchDecision | None,
        state_delta: ResearchStateDelta,
        model_turn: ResearchModelTurn | None,
    ) -> RewardFacts:
        validation = state_after.citation_validation
        prior_queries = {attempt.query for attempt in state_before.search_history}
        query_novelty = None
        if action is not None and action.query is not None:
            query_novelty = 0.0 if action.query in prior_queries else 1.0
        evidence_before = {item.evidence_id for item in state_before.evidence_ledger}
        evidence_added = sum(1 for item in state_after.evidence_ledger if item.evidence_id not in evidence_before)
        substantive_delta = state_delta.model_dump(mode="python")
        substantive_delta.pop("budget_consumption", None)
        substantive_delta = {key: value for key, value in substantive_delta.items() if value not in (None, [], {}, 0)}
        return RewardFacts(
            terminal_success=validation.passed if state_after.terminal_reason is not None and validation is not None else None,
            constraint_delta=len(state_before.unresolved_questions) - len(state_after.unresolved_questions),
            milestone_delta=1 if state_before.report is None and state_after.report is not None else 0,
            evidence_added=evidence_added,
            citation_supported=validation.metrics.supported_claim_count if validation is not None else 0,
            citation_invalid=validation.metrics.invalid_citation_count if validation is not None else 0,
            duplicate_action=bool(action and action.query and action.query in prior_queries),
            void_turn=not substantive_delta,
            search_query_novelty=query_novelty,
            tool_cost=0.0,
            context_tokens=state_delta.budget_consumption.context_tokens,
            trainable=model_turn.training_eligible if model_turn is not None else False,
            quarantine_reason=model_turn.quarantine_reason if model_turn is not None else None,
        )

    def _context_view(self, state: DeepResearchState, purpose: ResearchPromptPurpose):
        configured_budget = getattr(self.policy, "token_budget", state.budget.remaining_context_tokens)
        token_budget = min(
            state.budget.remaining_context_tokens,
            configured_budget if isinstance(configured_budget, int) and configured_budget > 0 else state.budget.remaining_context_tokens,
        )
        return build_research_policy_view(
            state,
            purpose=purpose,
            token_budget=token_budget,
        )

    @staticmethod
    def _context_tokens(view: object) -> int:
        model_dump_json = getattr(view, "model_dump_json")
        return max(1, (len(model_dump_json()) + 3) // 4)

    async def _store_context_view(self, state: DeepResearchState, *, context: object, graph_state: Mapping[str, Any]) -> ArtifactRef:
        purpose = getattr(context, "purpose")
        model_dump = getattr(context, "model_dump")
        return await self.artifact_store.store_json(
            state,
            artifact_type=ArtifactKind.CONTEXT_VIEW,
            artifact_key=f"research-{purpose.value}-context",
            payload=model_dump(mode="json"),
            summary=f"Secret-free DeepResearch {purpose.value} context view",
            idempotency_key=(
                f"research-context:{state.task.task_id}:{purpose.value}:"
                f"{int(graph_state.get('child_transition_sequence', 0))}:{canonical_hash(context)[:24]}"
            ),
        )

    @staticmethod
    def _coerce_policy_turn(
        value: object,
        *,
        state: DeepResearchState,
        context: object,
        purpose: ResearchPromptPurpose,
    ) -> PolicyTurnResult[Any]:
        if isinstance(value, PolicyTurnResult):
            return value
        context_hash = canonical_hash(context)
        return PolicyTurnResult(
            parsed_output=value,
            model_id="research-policy-adapter",
            model_revision=None,
            prompt_hash=canonical_hash(
                {
                    "provider": "research-policy-adapter",
                    "task_id": state.task.task_id,
                    "purpose": purpose.value,
                    "context_hash": context_hash,
                }
            ),
            context_hash=context_hash,
            trainable=False,
        )

    def _model_turn(self, turn: PolicyTurnResult[Any], purpose: ModelTurnPurpose) -> ResearchModelTurn:
        if turn.token_ids is None:
            training_eligible = False
            quarantine_reason = "missing_student_tokenization"
        elif not turn.token_role_spans:
            training_eligible = False
            quarantine_reason = "missing_token_role_spans"
        elif not turn.trainable:
            training_eligible = False
            quarantine_reason = "non_trainable_token_trace"
        elif purpose not in self.trainable_turn_purposes:
            training_eligible = False
            quarantine_reason = None
        elif not any(span.trainable for span in turn.token_role_spans):
            training_eligible = False
            quarantine_reason = "missing_trainable_assistant_span"
        else:
            training_eligible = True
            quarantine_reason = None
        return ResearchModelTurn(
            turn_purpose=purpose,
            model_id=turn.model_id,
            model_revision=turn.model_revision,
            prompt_template_hash=turn.prompt_hash,
            context_hash=turn.context_hash,
            raw_model_output_ref=turn.raw_model_output_ref,
            token_ids=list(turn.token_ids) if turn.token_ids is not None else None,
            token_logprobs=list(turn.token_logprobs) if turn.token_logprobs is not None else None,
            token_role_spans=[span.model_copy(deep=True) for span in turn.token_role_spans],
            usage=turn.usage.model_copy(deep=True),
            latency_ms=dict(turn.latency_ms),
            finish_reason=turn.finish_reason,
            provider_request_id=turn.provider_request_id,
            training_eligible=training_eligible,
            quarantine_reason=quarantine_reason,
            policy_version=self.metadata.policy_version,
            skill_catalog_hash=self.metadata.skill_catalog_hash,
            retriever_version=self.metadata.retriever_version,
            environment_snapshot_id=self.metadata.environment_snapshot_id,
            environment_snapshot_hash=self.metadata.environment_snapshot_hash,
            data_policy=self.metadata.data_policy.model_copy(deep=True),
        )

    async def _store_trace(self, state: DeepResearchState, raw_entries: object) -> ArtifactRef:
        values = raw_entries if isinstance(raw_entries, list) else []
        entries = [ResearchTraceEntry.model_validate(entry) for entry in values if isinstance(entry, dict)]
        return await self.trace_store.store(state, entries)

    @staticmethod
    def _load_state(graph_state: Mapping[str, Any]) -> DeepResearchState:
        return DeepResearchState.model_validate(graph_state["research_state"])

    @staticmethod
    def _dump_state(state: DeepResearchState) -> dict[str, Any]:
        return state.model_dump(mode="json")

    @staticmethod
    def _optional_decision(graph_state: Mapping[str, Any]) -> ResearchDecision | None:
        raw = graph_state.get("decision")
        return ResearchDecision.model_validate(raw) if raw else None

    @staticmethod
    def _graph_thread_id(task_id: str) -> str:
        return f"deep-research:{task_id}"

    @staticmethod
    def _recursion_limit(task: ResearchTaskPacket) -> int:
        """Derive scheduler headroom from the task's declared capability budget."""

        return max(
            64,
            12
            + task.max_turns * 6
            + task.max_search_turns * 2
            + task.max_page_reads * 2,
        )
