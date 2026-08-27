from __future__ import annotations

from pathlib import Path
from typing import Any

from studyhub_agent.benchmark_v2.evaluator_core import evaluate_contract
from studyhub_agent.benchmark_v2.metrics import EvaluationResult
from studyhub_agent.benchmark_v2.schema import GRADER_SCHEMA_VERSION, load_jsonl


def load_sealed_graders(path: str | Path) -> dict[str, dict[str, Any]]:
    graders: dict[str, dict[str, Any]] = {}
    for row in load_jsonl(path):
        if row.get("schema_version") != GRADER_SCHEMA_VERSION:
            raise ValueError(f"unsupported sealed grader schema: {row.get('schema_version')}")
        if row.get("split") not in {"sealed_a", "sealed_b"}:
            raise ValueError("sealed evaluator only accepts sealed_a/sealed_b graders")
        task_id = str(row["task_id"])
        if task_id in graders:
            raise ValueError(f"duplicate sealed grader: {task_id}")
        graders[task_id] = row
    return graders


def evaluate_sealed(
    *,
    final_answer: str,
    trace: dict[str, Any],
    final_state: dict[str, Any],
    grader: dict[str, Any],
) -> EvaluationResult:
    return evaluate_contract(
        final_answer=final_answer,
        trace=trace,
        final_state=final_state,
        grader=grader,
        sealed=True,
    )
