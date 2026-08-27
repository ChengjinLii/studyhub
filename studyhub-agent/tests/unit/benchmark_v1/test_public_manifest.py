from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from studyhub_agent.benchmark_v1.schema import BenchmarkTask, load_jsonl

PROJECT = Path(__file__).resolve().parents[3]
BENCHMARK = PROJECT / "benchmarks/studyhub-agent-v1"


def test_public_benchmark_v1_counts_and_contracts() -> None:
    manifest = json.loads((BENCHMARK / "manifest.json").read_text(encoding="utf-8"))
    regression = [BenchmarkTask.from_dict(row) for row in load_jsonl(BENCHMARK / "regression/tasks.jsonl")]
    development = [BenchmarkTask.from_dict(row) for row in load_jsonl(BENCHMARK / "development/tasks.jsonl")]
    assert manifest["counts"] == {"regression": 160, "development": 1005, "sealed": 500}
    assert len(regression) == 160
    assert len(development) == 1005
    assert len(Counter(task.capability_id for task in regression)) == 20
    assert len(Counter(task.capability_id for task in development)) == 20
    assert len({task.user_request for task in regression}) == len(regression)
    assert len({task.user_request for task in development}) == len(development)
