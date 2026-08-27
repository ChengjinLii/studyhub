from __future__ import annotations

from pathlib import Path
from typing import Any

from studyhub_agent.benchmark_v2.evaluator_core import evaluate_contract
from studyhub_agent.benchmark_v2.metrics import EvaluationResult
from studyhub_agent.benchmark_v2.schema import GRADER_SCHEMA_VERSION, load_jsonl


def load_development_graders(path: str | Path) -> dict[str, dict[str, Any]]:
    graders: dict[str, dict[str, Any]] = {}
    for row in load_jsonl(path):
        if row.get("schema_version") != GRADER_SCHEMA_VERSION:
            raise ValueError(f"unsupported grader schema: {row.get('schema_version')}")
        if row.get("split") not in {"regression", "development", "calibration_challenge"}:
            raise ValueError("development evaluator cannot load sealed graders")
        task_id = str(row["task_id"])
        if task_id in graders:
            raise ValueError(f"duplicate grader: {task_id}")
        graders[task_id] = row
    return graders


def evaluate_development(
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
        sealed=False,
    )
