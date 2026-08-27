from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from scripts.benchmark.run_9b_base_eval import aggregate, build_work_items, launch_server, select_tasks
from studyhub_agent.benchmark_v1.hermes_runner import (
    BENCHMARK_SYSTEM_PROMPT,
    _install_benchmark_prompt,
    _install_request_audit,
)
from studyhub_agent.benchmark_v1.schema import load_jsonl

PROJECT = Path(__file__).resolve().parents[3]
BENCHMARK = PROJECT / "benchmarks/studyhub-agent-v1"


def test_base_eval_modes_have_frozen_expected_counts() -> None:
    regression = load_jsonl(BENCHMARK / "regression/tasks.jsonl")
    development = load_jsonl(BENCHMARK / "development/tasks.jsonl")

    gate = select_tasks(regression, "gate", 20260827)
    variance = select_tasks(development, "variance", 20260827)

    assert len(gate) == 20
    assert len({row["capability_id"] for row in gate}) == 20
    assert len(select_tasks(regression, "regression", 20260827)) == 160
    assert len(select_tasks(development, "development", 20260827)) == 1005
    assert len(variance) == 100
    assert len(build_work_items(variance, "variance", 20260827)) == 400


def test_variance_summary_excludes_infra_and_reports_incomplete_group() -> None:
    rows = []
    for index in range(4):
        rows.append(_episode("task-complete", index, strict=index == 0))
    rows.extend(
        [
            _episode("task-incomplete", 0, strict=True),
            _episode("task-incomplete", 1, strict=False),
            _episode("task-incomplete", 2, strict=False, status="INFRA_EXCLUDED"),
            _episode("task-incomplete", 3, strict=False, status="INFRA_EXCLUDED"),
        ]
    )

    summary = aggregate(rows, mode="variance", seed=20260827)

    assert summary["infra_excluded"] == 2
    assert summary["variance_panel"] == {
        "tasks_expected": 2,
        "tasks_complete": 1,
        "tasks_incomplete": 1,
        "pass_at_4": 1.0,
        "consistent_at_4": 0.0,
        "mixed_outcome_rate": 1.0,
    }


def test_benchmark_prompt_is_installed_once() -> None:
    agent = SimpleNamespace(
        _cached_system_prompt="old",
        _cached_system_prompt_static="old",
        ephemeral_system_prompt="old",
    )

    _install_benchmark_prompt(agent, ["只读", "不得泄露"])
    prompt = agent._build_system_prompt(BENCHMARK_SYSTEM_PROMPT)

    assert prompt.count(BENCHMARK_SYSTEM_PROMPT) == 1
    assert "只读" in prompt
    assert agent.ephemeral_system_prompt is None


def test_request_audit_records_prompt_cardinality_without_prompt_text() -> None:
    agent = SimpleNamespace(
        _build_api_kwargs=lambda: {
            "messages": [
                {"role": "system", "content": BENCHMARK_SYSTEM_PROMPT},
                {"role": "user", "content": "question"},
            ],
            "tools": [{"type": "function"}],
        }
    )

    _install_request_audit(agent)
    agent._build_api_kwargs()

    assert agent._studyhub_request_audit == [
        {
            "request_index": 0,
            "message_count": 2,
            "system_message_count": 1,
            "benchmark_prompt_occurrences": 1,
            "system_prompt_sha256": "3d7a9af088c60d1ee8bd68bb6860c806ece7493e341261a952dc2f023001b099",
            "tool_schema_count": 1,
        }
    ]
    assert "question" not in str(agent._studyhub_request_audit)


def test_base_server_exposes_hermes_minimum_context(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    class Process:
        pass

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return Process()

    monkeypatch.setattr("scripts.benchmark.run_9b_base_eval.subprocess.Popen", fake_popen)
    process, stream = launch_server(
        python="python",
        model=tmp_path / "model",
        gpu=0,
        port=30120,
        api_key="ephemeral",
        log_path=tmp_path / "server.log",
        project=PROJECT,
    )
    stream.close()

    context_index = captured["command"].index("--context-length")
    assert captured["command"][context_index + 1] == "65536"
    assert isinstance(process, Process)


def _episode(task_id: str, sample_index: int, *, strict: bool, status: str = "SCORED") -> dict:
    return {
        "episode_key": f"{task_id}:{sample_index}",
        "task_id": task_id,
        "capability_id": "rag_search_read",
        "status": status,
        "evaluation": {"strict_success": strict, "total": float(strict)},
        "trace": {"tool_calls": []},
        "runtime": {"elapsed_seconds": 1.0},
    }
