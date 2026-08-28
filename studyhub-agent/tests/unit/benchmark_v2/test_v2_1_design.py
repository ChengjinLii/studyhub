from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.benchmark.v2_1.build_public_candidates import build_public_candidates
from scripts.benchmark.v2_1.preflight import validate_design

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_v2_1_design_is_independent_and_sealed_is_not_run() -> None:
    result = validate_design(PROJECT_ROOT)

    assert result["status"] == "PASS"
    assert result["design_status"] == "DESIGN_READY_DATA_NOT_BUILT"
    assert result["pipeline_stages"]["sealed_generation"].startswith("NOT_RUN")
    assert result["scope"]["sealed_accessed"] is False
    assert result["scope"]["model_claim_allowed"] is False


def test_public_builder_accepts_reviewed_development_candidate(tmp_path: Path) -> None:
    sources = tmp_path / "sources.jsonl"
    tasks = tmp_path / "tasks.jsonl"
    write_jsonl(
        sources,
        [
            {
                "source_group_id": "source-1",
                "split": "development",
                "license_status": "verified",
                "training_overlap": False,
                "independence_review": "PASS",
            }
        ],
    )
    write_jsonl(
        tasks,
        [
            {
                "task_id": "task-1",
                "split": "development",
                "source_group_id": "source-1",
                "capability_lane": "web_research",
                "independent_semantic_review": "PASS",
            }
        ],
    )

    rows, manifest = build_public_candidates(sources, tasks)

    assert len(rows) == 1
    assert manifest["sealed_accessed"] is False
    assert manifest["model_evaluation_allowed"] is False


def test_public_builder_refuses_sealed_or_oracle_fields(tmp_path: Path) -> None:
    sources = tmp_path / "sources.jsonl"
    tasks = tmp_path / "tasks.jsonl"
    write_jsonl(
        sources,
        [
            {
                "source_group_id": "source-1",
                "split": "development",
                "license_status": "verified",
                "training_overlap": False,
                "independence_review": "PASS",
            }
        ],
    )
    write_jsonl(
        tasks,
        [
            {
                "task_id": "task-1",
                "split": "development",
                "source_group_id": "source-1",
                "independent_semantic_review": "PASS",
                "gold_answer": "hidden",
            }
        ],
    )

    with pytest.raises(RuntimeError, match="hidden/oracle"):
        build_public_candidates(sources, tasks)
