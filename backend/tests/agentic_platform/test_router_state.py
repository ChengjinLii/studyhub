from __future__ import annotations

import copy
import json

import pytest

from ml.agentic_platform.sft.evaluate_router import _evaluation_messages
from ml.agentic_platform.sft.router_state import normalize_router_payload


def _payload() -> dict:
    return {
        "budget": {
            "remaining_candidate_slots": 10,
            "remaining_rounds": 3,
            "remaining_search_calls": 0,
            "remaining_tool_calls": 5,
        },
        "force_final": False,
        "tool_observations": [],
    }


@pytest.mark.parametrize(
    "status",
    [
        "available_but_not_yet_synthesized",
        "evidence_available",
        "pages_ready_for_context",
        "ready_for_synthesis",
    ],
)
def test_ready_evidence_statuses_are_normalized(status: str) -> None:
    payload = _payload()
    payload["tool_observations"] = [
        {
            "tool": "read_pdf_evidence",
            "result": {"evidence_status": status, "material_ids": [18, 20]},
        }
    ]

    result = normalize_router_payload(payload)

    assert result["routing_state"]["evidence_phase"] == "ready_for_synthesis"


def test_pending_evidence_is_distinct_from_ready() -> None:
    payload = _payload()
    payload["tool_observations"] = [
        {
            "tool": "read_pdf_evidence",
            "result": {
                "evidence_status": "not_collected",
                "material_ids": [18],
            },
        }
    ]

    result = normalize_router_payload(payload)

    assert result["routing_state"]["evidence_phase"] == "needs_page_evidence"


def test_force_final_wins_when_candidate_slots_remain() -> None:
    payload = _payload()
    payload["force_final"] = True
    payload["budget"].update(
        remaining_rounds=0,
        remaining_tool_calls=0,
        remaining_candidate_slots=10,
    )
    payload["tool_observations"] = [
        {
            "tool": "inspect_materials",
            "result": {"materials": [{"id": 18}, {"id": 20}]},
        }
    ]

    result = normalize_router_payload(payload)

    assert result["routing_state"] == {
        "version": "studyhub.router.state.v1",
        "must_finish_without_tools": True,
        "budget_phase": "must_finish",
        "evidence_phase": "not_observed",
        "candidate_phase": "details_observed",
        "memory_phase": "not_loaded",
    }


def test_normalization_is_idempotent_and_does_not_mutate_input() -> None:
    payload = _payload()
    payload["tool_observations"] = [
        {
            "tool": "read_memory",
            "result": {"owner": "current_synthetic_user"},
        }
    ]
    original = copy.deepcopy(payload)

    first = normalize_router_payload(payload)
    second = normalize_router_payload(first)

    assert payload == original
    assert second == first
    assert first["routing_state"]["memory_phase"] == "current_user_memory_loaded"


def test_evaluation_normalizes_only_the_user_payload() -> None:
    payload = _payload()
    record = {
        "messages": [
            {"role": "system", "content": "readonly router"},
            {"role": "user", "content": json.dumps(payload)},
            {"role": "assistant", "content": '{"mode":"final"}'},
        ]
    }

    messages = _evaluation_messages(
        record,
        normalize_routing_state=True,
    )

    assert [message["role"] for message in messages] == ["system", "user"]
    assert messages[0]["content"] == "readonly router"
    normalized = json.loads(messages[1]["content"])
    assert normalized["routing_state"]["version"] == "studyhub.router.state.v1"
    assert normalized["routing_state"]["budget_phase"] == "tools_available"


def test_evaluation_keeps_legacy_payload_when_normalization_is_disabled() -> None:
    payload = _payload()
    raw = json.dumps(payload)
    record = {
        "messages": [
            {"role": "system", "content": "readonly router"},
            {"role": "user", "content": raw},
            {"role": "assistant", "content": '{"mode":"final"}'},
        ]
    }

    messages = _evaluation_messages(
        record,
        normalize_routing_state=False,
    )

    assert messages[1]["content"] == raw
