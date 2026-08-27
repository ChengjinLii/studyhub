from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.data.build_runtime_sft_v3_1 import _select_teacher_rows
from scripts.data.verify_teacher_trajectories import accepted_record, verify_run
from scripts.data.select_runtime_sft_v3 import public_benchmark_prompt_hashes
from training.teacher.hermes_controller import collect_trajectory
from training.teacher.providers import (
    CodexSparkProvider,
    ResponsesAPIProvider,
    _codex_event_audit,
    _parse_action,
    build_provider,
)

ROOT = Path(__file__).resolve().parents[3]


def _teacher_root(tmp_path: Path, task_id: str) -> Path:
    root = tmp_path / "teacher"
    for directory in ("environments", "fixtures", "verifiers", "raw_runs"):
        (root / directory).mkdir(parents=True)
    tool = {
        "name": "teacher_fixture_lookup",
        "description": "Read one deterministic fixture value.",
        "capability": "function_call",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        },
    }
    (root / "environments" / f"{task_id}.json").write_text(
        json.dumps({"tools": [tool], "documents": []}),
        encoding="utf-8",
    )
    (root / "fixtures" / f"{task_id}.json").write_text(
        json.dumps(
            {
                "routes": [
                    {
                        "name": "teacher_fixture_lookup",
                        "arguments": {"key": "answer"},
                        "result": {"value": "42"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return root


def test_codex_event_audit_rejects_any_codex_tool_event() -> None:
    safe = "\n".join(
        [
            json.dumps({"type": "thread.started"}),
            json.dumps({"type": "item.completed", "item": {"type": "reasoning"}}),
            json.dumps({"type": "item.completed", "item": {"type": "agent_message"}}),
            json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 4}}),
        ]
    )
    unsafe = safe + "\n" + json.dumps(
        {"type": "item.completed", "item": {"type": "command_execution", "command": "cat secret"}}
    )

    assert _codex_event_audit(safe)["zero_codex_tool_events"] is True
    audit = _codex_event_audit(unsafe)
    assert audit["zero_codex_tool_events"] is False
    assert audit["forbidden_item_types"] == ["command_execution"]


def test_provider_action_decodes_strict_schema_argument_string() -> None:
    action = _parse_action(
        json.dumps(
            {
                "type": "tool_call",
                "name": "knowledge_search",
                "arguments": json.dumps({"query": "通信原理", "limit": 3}),
                "content": "",
            }
        )
    )

    assert action["arguments"] == {"query": "通信原理", "limit": 3}


def test_teacher_provider_availability_never_confuses_cli_with_responses_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert ResponsesAPIProvider().availability()["available"] is False
    assert CodexSparkProvider(command="missing-studyhub-codex").availability()["available"] is False
    compatible = build_provider("authorized-openai-compatible", model="fixture")
    assert compatible.availability()["available"] is False


def test_public_benchmark_hash_inventory_never_requires_sealed_task_files(tmp_path: Path) -> None:
    benchmark = tmp_path / "benchmarks/studyhub-agent-v2/development"
    benchmark.mkdir(parents=True)
    (benchmark / "tasks.jsonl").write_text(
        json.dumps({"task_id": "dev-1", "user_request": "public development task"}) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "public_files": {"development/tasks.jsonl": "fixture"},
        "counts": {
            "regression": 0,
            "development": 1,
            "calibration_challenge": 0,
            "sealed_a": 999,
            "sealed_b": 999,
        },
        "hidden_files": {
            "tasks/sealed_a.jsonl": "must-not-be-opened",
            "tasks/sealed_b.jsonl": "must-not-be-opened",
        },
    }

    hashes, count = public_benchmark_prompt_hashes(tmp_path, manifest)

    assert count == 1
    assert len(hashes) == 1


def test_actual_hermes_registry_executes_teacher_action_and_verifier_accepts(tmp_path: Path) -> None:
    checkout = ROOT / ".vendor/hermes-agent"
    if not checkout.is_dir():
        pytest.skip("pinned Hermes checkout is not installed")
    lock = json.loads((ROOT / "integrations/hermes/upstream.lock.json").read_text(encoding="utf-8"))
    task_id = "teacher-fixture"
    root = _teacher_root(tmp_path, task_id)
    task = {
        "schema_version": "studyhub.teacher-task.v1",
        "task_id": task_id,
        "family": "state_function",
        "user_request": "Look up the answer and report it.",
        "allowed_tools": ["teacher_fixture_lookup"],
        "max_steps": 3,
        "max_tool_calls": 2,
        "metadata": {
            "source_dataset": "fixture",
            "source_row_id": "fixture-row",
            "source_group_id": "fixture-group",
            "split": "train",
            "benchmark_overlap": False,
            "environment_id": task_id,
            "verifier_id": task_id,
        },
    }

    def choose_action(_task, _tools, _messages, turn):
        if turn == 0:
            return (
                {
                    "type": "tool_call",
                    "name": "teacher_fixture_lookup",
                    "arguments": {"key": "answer"},
                    "content": "",
                },
                {"interface": "fixture", "model": "fixture-teacher"},
            )
        return (
            {"type": "final", "name": "", "arguments": {}, "content": "The observed answer is 42."},
            {"interface": "fixture", "model": "fixture-teacher"},
        )

    run = collect_trajectory(
        task=task,
        root=root,
        hermes_checkout=checkout,
        hermes_commit=lock["commit"],
        choose_action=choose_action,
    )
    run.update(
        {
            "run_id": "fixture-run",
            "candidate_index": 0,
            "collection_mode": "teacher_rollout",
            "provider": {"interface": "fixture", "model": "fixture-teacher"},
            "collector_git_commit": "fixture-commit",
            "raw_run_path": "raw_runs/fixture-run.json",
        }
    )
    verifier = {
        "reference_final": "The observed answer is 42.",
        "expected_citations": [],
        "expected_tool_names": ["teacher_fixture_lookup"],
        "minimum_tool_calls": 1,
        "benchmark_prompt_overlap": False,
    }
    failures, diagnostics = verify_run(run, task, verifier)

    assert failures == []
    assert run["status"] == "COMPLETED"
    assert run["controller"]["hermes_registry_dispatch"] is True
    assert run["controller"]["tool_calls"] == 1
    record = accepted_record(run, task, verifier, diagnostics)
    assert record["quality_tier"] == "teacher_verified_complete"
    assert record["runtime_native"] is True


def test_accepted_direct_teacher_trajectory_is_not_falsely_runtime_native() -> None:
    run = {
        "run_id": "direct-run",
        "candidate_index": 0,
        "collection_mode": "teacher_rollout",
        "provider": {"interface": "fixture", "model": "fixture-teacher"},
        "collector_git_commit": "fixture-commit",
        "raw_run_path": "raw_runs/direct-run.json",
        "controller": {"hermes_commit": "fixture-hermes"},
        "tools": [],
        "messages": [
            {"role": "system", "content": "Answer directly when no tool is needed."},
            {"role": "user", "content": "What is two plus two?"},
            {"role": "assistant", "content": "Four."},
        ],
    }
    task = {
        "family": "direct_abstention",
        "metadata": {"source_group_id": "direct-fixture"},
    }

    record = accepted_record(run, task, {}, {})

    assert record["quality_tier"] == "teacher_verified_complete"
    assert record["runtime_native"] is False
    selected, drops = _select_teacher_rows(
        [record],
        base_content=set(),
        base_near=set(),
        public_benchmark_hashes=set(),
        max_rows_per_group=4,
    )
    assert [row["id"] for row in selected] == ["teacher-v1:direct-run"]
    assert drops == {}


def test_provider_failure_is_rejected_with_specific_taxonomy() -> None:
    task = {
        "family": "direct_abstention",
        "max_tool_calls": 1,
        "metadata": {"source_group_id": "fixture"},
    }
    run = {
        "status": "FAILED",
        "controller": {
            "hermes_registry_dispatch": True,
            "controller_errors": ["invalid_action_type"],
            "environment_errors": [],
            "runtime_errors": [],
            "invalid_tool_calls": 0,
            "tool_calls": 0,
        },
        "provider_events": [{"error_code": "codex_exec_failed"}],
        "messages": [],
        "final_answer": "",
    }
    failures, diagnostics = verify_run(
        run,
        task,
        {
            "reference_final": "fixture",
            "expected_citations": [],
            "expected_tool_names": [],
            "minimum_tool_calls": 0,
            "benchmark_prompt_overlap": False,
        },
    )

    assert "provider:codex_exec_failed" in failures
    assert diagnostics["provider_errors"] == ["codex_exec_failed"]
