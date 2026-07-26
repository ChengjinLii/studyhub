from __future__ import annotations

from collections.abc import Mapping
from typing import TypeVar

from app.models.agentic_runtime import AgentRunStatus, AgentStepStatus


class InvalidStatusTransition(ValueError):
    """Raised when a durable run or step is asked to move backwards or reopen."""


StatusT = TypeVar("StatusT", AgentRunStatus, AgentStepStatus)


RUN_STATUS_TRANSITIONS: Mapping[AgentRunStatus, frozenset[AgentRunStatus]] = {
    AgentRunStatus.CREATED: frozenset({AgentRunStatus.QUEUED, AgentRunStatus.RUNNING, AgentRunStatus.CANCELLED, AgentRunStatus.FAILED}),
    AgentRunStatus.QUEUED: frozenset({AgentRunStatus.RUNNING, AgentRunStatus.CANCELLING, AgentRunStatus.CANCELLED, AgentRunStatus.FAILED}),
    AgentRunStatus.RUNNING: frozenset(
        {AgentRunStatus.WAITING, AgentRunStatus.CANCELLING, AgentRunStatus.COMPLETED, AgentRunStatus.FAILED, AgentRunStatus.CANCELLED}
    ),
    AgentRunStatus.WAITING: frozenset({AgentRunStatus.QUEUED, AgentRunStatus.RUNNING, AgentRunStatus.CANCELLING, AgentRunStatus.CANCELLED, AgentRunStatus.FAILED}),
    AgentRunStatus.CANCELLING: frozenset({AgentRunStatus.CANCELLED, AgentRunStatus.FAILED}),
    AgentRunStatus.COMPLETED: frozenset(),
    AgentRunStatus.FAILED: frozenset(),
    AgentRunStatus.CANCELLED: frozenset(),
}

STEP_STATUS_TRANSITIONS: Mapping[AgentStepStatus, frozenset[AgentStepStatus]] = {
    AgentStepStatus.PENDING: frozenset({AgentStepStatus.RUNNING, AgentStepStatus.SKIPPED, AgentStepStatus.CANCELLED}),
    AgentStepStatus.RUNNING: frozenset(
        {AgentStepStatus.WAITING, AgentStepStatus.COMPLETED, AgentStepStatus.FAILED, AgentStepStatus.CANCELLED}
    ),
    AgentStepStatus.WAITING: frozenset({AgentStepStatus.RUNNING, AgentStepStatus.FAILED, AgentStepStatus.CANCELLED}),
    AgentStepStatus.COMPLETED: frozenset(),
    AgentStepStatus.FAILED: frozenset(),
    AgentStepStatus.SKIPPED: frozenset(),
    AgentStepStatus.CANCELLED: frozenset(),
}


def _assert_transition(
    *,
    current: StatusT,
    target: StatusT,
    transitions: Mapping[StatusT, frozenset[StatusT]],
    entity_name: str,
) -> None:
    if current == target:
        return
    if target not in transitions[current]:
        raise InvalidStatusTransition(f"invalid {entity_name} status transition: {current.value} -> {target.value}")


def assert_run_status_transition(current: AgentRunStatus | str, target: AgentRunStatus | str) -> None:
    _assert_transition(
        current=AgentRunStatus(current),
        target=AgentRunStatus(target),
        transitions=RUN_STATUS_TRANSITIONS,
        entity_name="run",
    )


def assert_step_status_transition(current: AgentStepStatus | str, target: AgentStepStatus | str) -> None:
    _assert_transition(
        current=AgentStepStatus(current),
        target=AgentStepStatus(target),
        transitions=STEP_STATUS_TRANSITIONS,
        entity_name="step",
    )
