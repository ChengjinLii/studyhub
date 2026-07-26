from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.agentic_platform.domain.decision import (
    AgentActionType,
    AgentDecision,
    AgentOutput,
    ExpectedStateChange,
    SubAgentTaskPacket,
)
from app.agentic_platform.domain.state import ApprovalRequest, EventWait, UserInputRequest
from app.agentic_platform.domain.transition import TokenRole, TokenRoleSpan
from tests.agentic_platform.factories import artifact_ref, transition


def _expected_change() -> ExpectedStateChange:
    return ExpectedStateChange(summary="A bounded state update is expected.")


@pytest.mark.parametrize(
    ("action_type", "payload"),
    [
        (AgentActionType.EXECUTE_SKILL, {"skill_name": "research.search", "arguments": {"query": "signals"}}),
        (
            AgentActionType.DELEGATE,
            {
                "delegate_agent": "researcher",
                "task_packet": SubAgentTaskPacket(task_id="subtask-1", objective="Find evidence", max_turns=2),
            },
        ),
        (AgentActionType.ASK_USER, {"user_request": UserInputRequest(request_id="input-1", prompt="Choose scope")}),
        (
            AgentActionType.REQUEST_APPROVAL,
            {"approval_request": ApprovalRequest(approval_id="approval-1", action_summary="Use a paid source")},
        ),
        (AgentActionType.WAIT_EVENT, {"event_wait": EventWait(event_name="material-indexed")}),
        (AgentActionType.FINALIZE, {"final_output": AgentOutput(summary="Completed", artifact_refs=[artifact_ref("result")])}),
    ],
)
def test_action_union_accepts_each_valid_specialized_payload(action_type: AgentActionType, payload: dict) -> None:
    decision = AgentDecision(
        action_type=action_type,
        rationale_summary="A concise rationale only.",
        expected_state_change=_expected_change(),
        **payload,
    )

    assert decision.action_type is action_type


def test_action_union_rejects_missing_and_unrelated_payloads() -> None:
    with pytest.raises(ValidationError, match="execute_skill requires"):
        AgentDecision(
            action_type=AgentActionType.EXECUTE_SKILL,
            rationale_summary="Run the search.",
            expected_state_change=_expected_change(),
            skill_name="research.search",
        )
    with pytest.raises(ValidationError, match="review does not allow"):
        AgentDecision(
            action_type=AgentActionType.REVIEW,
            rationale_summary="Review evidence.",
            expected_state_change=_expected_change(),
            skill_name="research.search",
        )


def test_transition_round_trips_and_keeps_raw_token_roles_consistent() -> None:
    event = transition().model_copy(
        update={
            "token_ids": [11, 12, 13, 14],
            "token_logprobs": [-0.1, -0.2, -0.3, -0.4],
            "token_role_spans": [
                TokenRoleSpan(role=TokenRole.SYSTEM, start=0, end=2, trainable=False),
                TokenRoleSpan(role=TokenRole.ASSISTANT_ACTION, start=2, end=4, trainable=True),
            ],
            "exported_at": datetime(2026, 7, 26, tzinfo=UTC),
        }
    )

    round_tripped = type(event).model_validate_json(event.model_dump_json())

    assert round_tripped == event
    assert round_tripped.token_ids == [11, 12, 13, 14]


def test_transition_rejects_invalid_token_trace_and_trainability() -> None:
    with pytest.raises(ValidationError, match="fixed trainable"):
        TokenRoleSpan(role=TokenRole.ASSISTANT_FINAL, start=0, end=1, trainable=False)
    with pytest.raises(ValidationError, match="raw token IDs"):
        type(transition()).model_validate(
            transition().model_dump(mode="python") | {
                "token_logprobs": [-0.1],
                "token_ids": None,
            }
        )
