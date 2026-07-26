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
    ResearchStateDelta,
    ResearchTaskPacket,
    apply_research_delta,
    initial_research_state,
)


class ResearchGraphState(TypedDict, total=False):
    """Scheduler state only; ``research_state`` remains the domain authority."""

    research_state: dict[str, Any]
    decision: dict[str, Any]
    trace: list[dict[str, Any]]
    report: dict[str, Any]
    terminal_reason: str


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
    ) -> None:
        self.policy = policy
        self.router = router
        self.trace_store = trace_store or InMemoryResearchTraceStore()
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
            context_tokens = self._context_tokens(state_before, ResearchPromptPurpose.PLANNER)
            plan = await self.policy.create_plan(state_before)
            state_after = apply_research_delta(
                state_before,
                ResearchStateDelta(
                    plan=plan,
                    budget_consumption=ResearchBudgetConsumption(turns=1, context_tokens=context_tokens),
                ),
            )
            summary = f"Research plan {plan.plan_id} version {plan.version} is available for policy selection."
            return Command(
                update=self._state_update(
                    graph_state,
                    state_before,
                    state_after,
                    node_name="planner",
                    summary=summary,
                ),
                goto="policy",
            )
        except Exception as exc:  # noqa: BLE001 - adapter/model detail is intentionally not emitted.
            return self._to_finalizer(graph_state, state_before, f"research_planner_failed:{exc.__class__.__name__}")

    async def _policy(self, graph_state: Mapping[str, Any]) -> Command:
        state_before = self._load_state(graph_state)
        if state_before.budget.remaining_turns <= 0 or state_before.budget.remaining_context_tokens <= 0:
            return self._to_finalizer(graph_state, state_before, "research_budget_exhausted")
        try:
            context_tokens = self._context_tokens(state_before, ResearchPromptPurpose.POLICY)
            decision = await self.policy.decide(state_before)
            state_after = apply_research_delta(
                state_before,
                ResearchStateDelta(budget_consumption=ResearchBudgetConsumption(turns=1, context_tokens=context_tokens)),
            )
        except Exception as exc:  # noqa: BLE001
            return self._to_finalizer(graph_state, state_before, f"research_policy_failed:{exc.__class__.__name__}")

        update = self._state_update(
            graph_state,
            state_before,
            state_after,
            node_name="policy",
            action=decision,
            summary="Policy selected an atomic research action.",
        )
        update["decision"] = decision.model_dump(mode="json")
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
            update=self._state_update(
                graph_state,
                state_before,
                state_after,
                node_name="executor",
                action=decision,
                summary=result.summary,
                error_code=result.error_code,
            ),
            goto="policy",
        )

    async def _finalizer(self, graph_state: Mapping[str, Any]) -> Command:
        state_before = self._load_state(graph_state)
        reason = str(graph_state.get("terminal_reason") or "finalized")
        report: ResearchReport
        state_after = state_before
        if reason != "policy_abort" and state_before.budget.remaining_turns > 0 and state_before.budget.remaining_context_tokens > 0:
            try:
                context_tokens = self._context_tokens(state_before, ResearchPromptPurpose.FINALIZER)
                report = await self.policy.finalize(state_before)
                state_after = apply_research_delta(
                    state_before,
                    ResearchStateDelta(
                        report=report,
                        budget_consumption=ResearchBudgetConsumption(turns=1, context_tokens=context_tokens),
                    ),
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
        state_after = apply_research_delta(
            state_after,
            ResearchStateDelta(
                report=report,
                citation_validation=validation,
                terminal_reason=reason,
            ),
        )
        update = self._state_update(
            graph_state,
            state_before,
            state_after,
            node_name="finalizer",
            action=self._optional_decision(graph_state),
            summary=validation.summary,
        )
        update.update(
            {
                "report": report.model_dump(mode="json"),
                "terminal_reason": reason,
            }
        )
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

    def _state_update(
        self,
        graph_state: Mapping[str, Any],
        state_before: DeepResearchState,
        state_after: DeepResearchState,
        *,
        node_name: str,
        summary: str,
        action: ResearchDecision | None = None,
        error_code: str | None = None,
    ) -> dict[str, Any]:
        entry = ResearchTraceEntry(
            node_name=node_name,
            turn_index=len(graph_state.get("trace", [])),
            action_type=action.action_type if action else None,
            rationale_summary=action.rationale_summary if action else None,
            summary=summary,
            state_before_hash=canonical_hash(state_before),
            state_after_hash=canonical_hash(state_after),
            error_code=error_code,
        )
        return {
            "research_state": self._dump_state(state_after),
            "trace": [*graph_state.get("trace", []), entry.model_dump(mode="json")],
        }

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

    @staticmethod
    def _context_tokens(state: DeepResearchState, purpose: ResearchPromptPurpose) -> int:
        view = build_research_policy_view(
            state,
            purpose=purpose,
            token_budget=state.budget.remaining_context_tokens,
        )
        return max(1, (len(view.model_dump_json()) + 3) // 4)
