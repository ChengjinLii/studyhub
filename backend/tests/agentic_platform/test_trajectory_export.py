from __future__ import annotations

import asyncio

from app.agentic_platform.domain.transition import AgentTransitionEvent, ModelTurnPurpose, TokenRole, TokenRoleSpan
from app.agentic_platform.simulation.trajectory import ModelIORecord, TransitionJsonlSink
from tests.agentic_platform.factories import transition


def _tokenized_transition(*, thread_id: str = "thread-1", run_id: str = "run-1", transition_id: str = "transition-1") -> AgentTransitionEvent:
    event = transition()
    return AgentTransitionEvent.model_validate(
        event.model_dump(mode="python")
        | {
            "thread_id": thread_id,
            "run_id": run_id,
            "transition_id": transition_id,
            "token_ids": [101, 102, 103, 104, 105],
            "token_logprobs": [-0.1, -0.2, -0.3, -0.4, -0.5],
            "token_role_spans": [
                TokenRoleSpan(role=TokenRole.SYSTEM, start=0, end=1, trainable=False),
                TokenRoleSpan(role=TokenRole.TOOL_OBSERVATION, start=1, end=3, trainable=False),
                TokenRoleSpan(role=TokenRole.ASSISTANT_ACTION, start=3, end=4, trainable=True),
                TokenRoleSpan(role=TokenRole.ASSISTANT_FINAL, start=4, end=5, trainable=True),
            ],
        }
    )


def test_transition_sink_preserves_raw_token_ids_and_masks_observations(tmp_path) -> None:
    event = _tokenized_transition()
    sink = TransitionJsonlSink(tmp_path / "trajectory-export")

    asyncio.run(sink.emit(event))
    asyncio.run(sink.emit(event))  # Idempotent retry must not duplicate JSONL rows.

    paths = sink.paths_for_event(event)
    transition_rows = paths.transitions_path.read_text(encoding="utf-8").splitlines()
    model_rows = paths.model_io_path.read_text(encoding="utf-8").splitlines()
    exported_event = AgentTransitionEvent.model_validate_json(transition_rows[0])
    model_record = ModelIORecord.model_validate_json(model_rows[0])
    manifest = sink.manifest_for_event(event)

    assert len(transition_rows) == 1
    assert len(model_rows) == 1
    assert exported_event.token_ids == [101, 102, 103, 104, 105]
    assert model_record.token_ids == [101, 102, 103, 104, 105]
    assert model_record.trainable_token_mask == [False, False, False, True, True]
    assert manifest is not None
    assert manifest.transition_count == 1
    assert manifest.model_io_count == 1


def test_corrupted_trajectory_is_quarantined_before_a_fresh_trace_is_written(tmp_path) -> None:
    event = _tokenized_transition()
    sink = TransitionJsonlSink(tmp_path / "trajectory-export")
    paths = sink.paths_for_event(event)
    paths.transitions_path.parent.mkdir(parents=True)
    paths.transitions_path.write_text("{not-json}\n", encoding="utf-8")

    asyncio.run(sink.emit(event))

    assert paths.transitions_path.exists()
    assert AgentTransitionEvent.model_validate_json(paths.transitions_path.read_text(encoding="utf-8").strip()) == event
    quarantines = list(paths.quarantine_root.iterdir())
    assert len(quarantines) == 1
    assert (quarantines[0] / "quarantine.json").exists()
    assert (quarantines[0] / paths.transitions_path.name).exists()


def test_trajectory_paths_are_isolated_by_thread_and_run(tmp_path) -> None:
    first = _tokenized_transition(thread_id="thread-a", run_id="run-a", transition_id="transition-a")
    second = _tokenized_transition(thread_id="thread-b", run_id="run-b", transition_id="transition-b")
    sink = TransitionJsonlSink(tmp_path / "trajectory-export")

    asyncio.run(sink.emit(first))
    asyncio.run(sink.emit(second))

    first_paths = sink.paths_for_event(first)
    second_paths = sink.paths_for_event(second)
    assert first_paths.trajectory_id != second_paths.trajectory_id
    assert first_paths.transitions_path != second_paths.transitions_path
    assert first_paths.transitions_path.read_text(encoding="utf-8").count("\n") == 1
    assert second_paths.transitions_path.read_text(encoding="utf-8").count("\n") == 1


def test_standalone_planner_model_io_is_retained_without_local_tokens(tmp_path) -> None:
    action = _tokenized_transition()
    planner_turn = action.model_turn_event().model_copy(
        update={
            "model_turn_id": "model-turn-planner-1",
            "transition_id": None,
            "turn_purpose": ModelTurnPurpose.PLANNER,
            "token_ids": None,
            "token_logprobs": None,
            "token_role_spans": [],
            "training_eligible": False,
            "quarantine_reason": "missing_student_tokenization",
        }
    )
    sink = TransitionJsonlSink(tmp_path / "trajectory-export")

    asyncio.run(sink.emit_model_turn(planner_turn))
    asyncio.run(sink.emit(action))

    paths = sink.paths_for_event(action)
    records = [ModelIORecord.model_validate_json(line) for line in paths.model_io_path.read_text(encoding="utf-8").splitlines()]
    manifest = sink.manifest_for_event(action)
    assert len(records) == 2
    assert records[0].transition_id is None
    assert records[0].training_eligible is False
    assert records[0].quarantine_reason == "missing_student_tokenization"
    assert manifest is not None
    assert manifest.model_io_count == 2
