from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

TRAJECTORY_SCHEMA_VERSION = "studyhub.trajectory.v1"
EVENT_TYPES = frozenset(
    {
        "run_started",
        "user_message",
        "memory_recall",
        "model_action",
        "tool_call",
        "tool_result",
        "final_answer",
        "reward_assigned",
        "run_finished",
    }
)


@dataclass(frozen=True, slots=True)
class TrajectoryEvent:
    schema_version: str
    run_id: str
    episode_id: str
    task_id: str
    group_id: str | None
    step_id: int
    policy: dict[str, Any] = field(default_factory=dict)
    event_type: str = "model_action"
    state: dict[str, Any] = field(default_factory=dict)
    action: dict[str, Any] = field(default_factory=dict)
    observation: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    reward: float | None = None

    def __post_init__(self) -> None:
        if self.schema_version != TRAJECTORY_SCHEMA_VERSION:
            raise ValueError(f"unsupported trajectory schema: {self.schema_version}")
        if not all(value.strip() for value in (self.run_id, self.episode_id, self.task_id)):
            raise ValueError("run_id, episode_id, and task_id are required")
        if self.group_id is not None and not self.group_id.strip():
            raise ValueError("group_id must be null or non-empty")
        if self.step_id < 0 or self.latency_ms < 0:
            raise ValueError("step_id and latency_ms must be non-negative")
        if self.event_type not in EVENT_TYPES:
            raise ValueError(f"unsupported trajectory event type: {self.event_type}")
        if self.reward is not None and not -1.0 <= self.reward <= 1.0:
            raise ValueError("event reward must be in [-1, 1]")
        for name in ("policy", "state", "action", "observation", "usage"):
            if not isinstance(getattr(self, name), dict):
                raise TypeError(f"{name} must be an object")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> TrajectoryEvent:
        return cls(
            schema_version=str(value["schema_version"]),
            run_id=str(value["run_id"]),
            episode_id=str(value["episode_id"]),
            task_id=str(value["task_id"]),
            group_id=None if value.get("group_id") is None else str(value["group_id"]),
            step_id=int(value["step_id"]),
            policy=dict(value.get("policy", {})),
            event_type=str(value["event_type"]),
            state=dict(value.get("state", {})),
            action=dict(value.get("action", {})),
            observation=dict(value.get("observation", {})),
            usage=dict(value.get("usage", {})),
            latency_ms=float(value.get("latency_ms", 0.0)),
            reward=None if value.get("reward") is None else float(value["reward"]),
        )
