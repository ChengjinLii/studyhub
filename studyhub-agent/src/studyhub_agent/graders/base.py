from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict

from studyhub_agent.contracts.episode import Episode, FailureOwner


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TaskSpec(_Frozen):
    task_id: str
    expected_final: str | None = None
    required_tools: tuple[str, ...] = ()


class GradeResult(_Frozen):
    strict_pass: bool
    hard_gates: dict[str, bool]
    scores: dict[str, float]
    failure_owner: FailureOwner
    evidence: tuple[str, ...] = ()


class Grader(Protocol):
    def grade(self, episode: Episode, task: TaskSpec) -> GradeResult: ...
