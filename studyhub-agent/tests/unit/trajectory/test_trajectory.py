import json

import pytest

from studyhub_agent.trajectory import TRAJECTORY_SCHEMA_VERSION, TrajectoryEvent, TrajectoryRecorder, read_trajectory


def test_trajectory_round_trip_and_monotonic_steps(tmp_path) -> None:
    recorder = TrajectoryRecorder(
        run_id="run-001",
        episode_id="episode-001",
        task_id="case-001",
        policy={"model": "fake", "checkpoint": "none", "prompt_version": "studyhub-v2"},
    )
    recorder.record("run_started", state={"seed": 7})
    recorder.record("tool_call", action={"name": "knowledge_search", "arguments": {"query": "通信原理"}})
    recorder.record("tool_result", observation={"source_ids": ["material:101:p1:c0"]}, latency_ms=3.5)
    recorder.record("final_answer", action={"text": "复习建议 [source:material:101:p1:c0]"})
    recorder.record("run_finished", reward=0.75)

    path = recorder.write_jsonl(tmp_path / "trajectory.jsonl")
    loaded = read_trajectory(path)

    assert [event.step_id for event in loaded] == list(range(5))
    assert loaded == list(recorder.events)
    assert all(event.schema_version == TRAJECTORY_SCHEMA_VERSION for event in loaded)
    assert len(path.read_text(encoding="utf-8").splitlines()) == 5


def test_trajectory_rejects_unknown_events_and_out_of_range_rewards() -> None:
    base = {
        "schema_version": TRAJECTORY_SCHEMA_VERSION,
        "run_id": "run-001",
        "episode_id": "episode-001",
        "task_id": "case-001",
        "group_id": None,
        "step_id": 0,
        "policy": {},
        "event_type": "unknown",
        "state": {},
        "action": {},
        "observation": {},
        "usage": {},
        "latency_ms": 0,
        "reward": None,
    }
    with pytest.raises(ValueError):
        TrajectoryEvent.from_dict(base)
    base["event_type"] = "reward_assigned"
    base["reward"] = 1.1
    with pytest.raises(ValueError):
        TrajectoryEvent.from_dict(json.loads(json.dumps(base)))
