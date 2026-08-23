from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from studyhub_agent.trajectory.schema import TRAJECTORY_SCHEMA_VERSION, TrajectoryEvent


class TrajectoryRecorder:
    """Append-only in-memory recorder with explicit JSONL persistence."""

    def __init__(
        self,
        *,
        run_id: str,
        episode_id: str,
        task_id: str,
        policy: dict[str, Any],
        group_id: str | None = None,
    ) -> None:
        self.run_id = run_id
        self.episode_id = episode_id
        self.task_id = task_id
        self.group_id = group_id
        self.policy = dict(policy)
        self._events: list[TrajectoryEvent] = []

    @property
    def events(self) -> tuple[TrajectoryEvent, ...]:
        return tuple(self._events)

    def record(
        self,
        event_type: str,
        *,
        state: dict[str, Any] | None = None,
        action: dict[str, Any] | None = None,
        observation: dict[str, Any] | None = None,
        usage: dict[str, Any] | None = None,
        latency_ms: float = 0.0,
        reward: float | None = None,
    ) -> TrajectoryEvent:
        event = TrajectoryEvent(
            schema_version=TRAJECTORY_SCHEMA_VERSION,
            run_id=self.run_id,
            episode_id=self.episode_id,
            task_id=self.task_id,
            group_id=self.group_id,
            step_id=len(self._events),
            policy=dict(self.policy),
            event_type=event_type,
            state=dict(state or {}),
            action=dict(action or {}),
            observation=dict(observation or {}),
            usage=dict(usage or {}),
            latency_ms=latency_ms,
            reward=reward,
        )
        self._events.append(event)
        return event

    def write_jsonl(self, path: str | Path) -> Path:
        destination = Path(path).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            for event in self._events:
                handle.write(json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
        temporary.replace(destination)
        return destination


def read_trajectory(path: str | Path) -> list[TrajectoryEvent]:
    source = Path(path)
    return [
        TrajectoryEvent.from_dict(json.loads(line))
        for line in source.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
