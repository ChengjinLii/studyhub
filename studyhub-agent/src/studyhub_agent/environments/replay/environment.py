from __future__ import annotations

from types import MappingProxyType
from typing import Any

from studyhub_agent.contracts.episode import EpisodeSpec, Observation, ToolCall
from studyhub_agent.contracts.tools import ToolSpec
from studyhub_agent.environments.replay.handlers import HANDLERS, ReplayContext, ReplayState
from studyhub_agent.environments.replay.index import Bm25Index
from studyhub_agent.environments.replay.snapshot import ReplaySnapshot, snapshot_digest
from studyhub_agent.guardrails.privacy import sanitize_output
from studyhub_agent.tools.specs import TOOL_SPECS


class ReplayEnvironment:
    """Deterministic, gated replay of a frozen StudyHub snapshot."""

    def __init__(self, snapshot: ReplaySnapshot) -> None:
        self._context = ReplayContext(
            snapshot=snapshot,
            index=Bm25Index(snapshot.materials),
            materials=MappingProxyType({row.material_id: row for row in snapshot.materials}),
            pages=MappingProxyType({page.url: page for page in snapshot.web_pages}),
        )
        self._digest = snapshot_digest(snapshot)
        self._state: ReplayState | None = None
        self._calls: tuple[str, ...] = ()

    def reset(self, spec: EpisodeSpec) -> None:
        memory = self._context.snapshot.memory.get(spec.principal.principal_id, {})
        self._state = ReplayState(principal=spec.principal, memory=MappingProxyType(dict(memory)))
        self._calls = ()

    def tool_specs(self) -> tuple[ToolSpec, ...]:
        return TOOL_SPECS

    def execute(self, call: ToolCall) -> Observation:
        if self._state is None:
            raise RuntimeError("ReplayEnvironment.execute called before reset")
        self._calls = (*self._calls, call.name)
        handler = HANDLERS.get(call.name)
        if handler is None:
            return Observation(
                call_id=call.call_id,
                name=call.name,
                ok=False,
                payload={"error": "unknown_tool"},
                error_code="unknown_tool",
            )
        ok, payload, error_code, self._state = handler(self._context, self._state, dict(call.arguments))
        return Observation(
            call_id=call.call_id, name=call.name, ok=ok, payload=sanitize_output(payload), error_code=error_code
        )

    def trace(self) -> dict[str, Any]:
        state = self._state
        return {
            "snapshot_id": self._context.snapshot.snapshot_id,
            "snapshot_digest": self._digest,
            "discovered_material_ids": sorted(state.discovered) if state else [],
            "read_material_ids": list(state.read) if state else [],
            "tool_calls": list(self._calls),
        }
