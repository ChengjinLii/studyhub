from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel, Field

from app.agentic_platform.domain import DomainModel
from app.agentic_platform.domain.artifact import ArtifactRef
from app.agentic_platform.domain.decision import SubAgentTaskPacket as AgentSubAgentTaskPacket


TaskT = TypeVar("TaskT", bound=BaseModel)
ResultT = TypeVar("ResultT", bound=BaseModel)


class SubAgentTaskPacket(AgentSubAgentTaskPacket):
    """Bounded extension of the domain delegation packet, never a whole Thread."""

    schema_version: str = "1.0"
    subagent_name: str = Field(min_length=1, max_length=128)
    admin_actor_id: int = Field(gt=0)
    parent_transition_id: str | None = Field(default=None, max_length=128)


class SubAgentResult(DomainModel):
    """Structured handoff back to a parent Agent; persistence stays outside it."""

    schema_version: str = "1.0"
    task_id: str = Field(min_length=1, max_length=128)
    subagent_name: str = Field(min_length=1, max_length=128)
    parent_transition_id: str | None = Field(default=None, max_length=128)
    summary: str = Field(min_length=1, max_length=2_000)
    artifact_refs: list[ArtifactRef] = Field(default_factory=list)
    turns_used: int = Field(ge=0)


class SubAgent(Protocol[TaskT, ResultT]):
    async def run(self, task: TaskT) -> ResultT:
        ...
