"""Deterministic routing-state normalization for StudyHub Agent inputs.

The normalizer converts heterogeneous tool-result vocabulary into a small
runtime contract. It uses only request state and tool observations; labels,
model predictions, production services, and user data are not consulted.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any


ROUTING_STATE_VERSION = "studyhub.router.state.v1"
READY_EVIDENCE_STATUSES = {
    "available",
    "available_but_not_yet_synthesized",
    "evidence_available",
    "pages_ready_for_context",
    "ready",
    "ready_for_synthesis",
}
PENDING_EVIDENCE_STATUSES = {
    "missing",
    "needs_collection",
    "not_available",
    "not_collected",
    "pending",
}


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _observations(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    value = payload.get("tool_observations")
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _evidence_phase(observations: Sequence[Mapping[str, Any]]) -> str:
    evidence_observations = [
        observation
        for observation in observations
        if observation.get("tool") == "read_pdf_evidence"
    ]
    if not evidence_observations:
        return "not_observed"

    result = _mapping(evidence_observations[-1].get("result"))
    status = str(result.get("evidence_status") or "").strip().lower()
    if status in READY_EVIDENCE_STATUSES:
        return "ready_for_synthesis"
    if status in PENDING_EVIDENCE_STATUSES:
        return "needs_page_evidence"
    if result.get("executed") is True and (
        result.get("pages") or result.get("material_ids")
    ):
        return "ready_for_synthesis"
    if result.get("executed") is False:
        return "needs_page_evidence"
    return "observed_unspecified"


def _candidate_phase(observations: Sequence[Mapping[str, Any]]) -> str:
    for observation in reversed(observations):
        result = _mapping(observation.get("result"))
        if observation.get("tool") == "inspect_materials" and (
            result.get("materials") or result.get("material_ids")
        ):
            return "details_observed"
        if observation.get("tool") == "search_materials" and (
            result.get("candidates") or result.get("materials")
        ):
            return "search_results_only"
    return "not_observed"


def _memory_phase(observations: Sequence[Mapping[str, Any]]) -> str:
    if any(
        observation.get("tool") == "read_memory"
        for observation in observations
    ):
        return "current_user_memory_loaded"
    return "not_loaded"


def normalize_router_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return a normalized copy of one router user payload."""

    normalized = copy.deepcopy(dict(payload))
    budget = _mapping(normalized.get("budget"))
    observations = _observations(normalized)
    force_final = normalized.get("force_final") is True
    remaining_rounds = budget.get("remaining_rounds")
    remaining_tool_calls = budget.get("remaining_tool_calls")
    must_finish = force_final or remaining_rounds == 0 or remaining_tool_calls == 0
    normalized["routing_state"] = {
        "version": ROUTING_STATE_VERSION,
        "must_finish_without_tools": must_finish,
        "budget_phase": "must_finish" if must_finish else "tools_available",
        "evidence_phase": _evidence_phase(observations),
        "candidate_phase": _candidate_phase(observations),
        "memory_phase": _memory_phase(observations),
    }
    return normalized
