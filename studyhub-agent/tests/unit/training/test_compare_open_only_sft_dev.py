from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.train.compare_open_only_sft_dev import compare


def _episode(task_id: str, *, success: bool, capability: str = "factual_passage_retrieval") -> dict:
    return {
        "task_id": task_id,
        "capability_id": capability,
        "status": "SCORED",
        "final_answer": "answer",
        "trace": {
            "tool_calls": [
                {
                    "name": "knowledge_search",
                    "error": None,
                    "observation": {"ok": True, "results": [{"source_id": "s1"}]},
                },
                {
                    "name": "knowledge_read",
                    "error": None,
                    "observation": {"ok": True, "text": "evidence"},
                },
            ],
            "policy_errors": [],
            "environment_errors": [],
            "runtime_errors": [],
        },
        "evaluation": {
            "strict_success": success,
            "diagnostic_scalar": 1.0 if success else 0.2,
            "tool_validity": 1.0,
            "tool_calls": 2,
            "realized_successful_policy_steps": 2,
            "hard_gate_reasons": [],
            "diagnostics": {
                "sealed": False,
                "process": {"requirement_failures": []},
            },
        },
    }


def _run(path: Path, *, successes: set[int], benchmark_hash: str = "frozen-v2") -> Path:
    path.mkdir()
    rows = [_episode(f"task-{index:02d}", success=index in successes) for index in range(51)]
    (path / "episodes.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    (path / "summary.json").write_text(
        json.dumps(
            {
                "mode": "development",
                "run_id": path.name,
                "model": path.name,
                "benchmark_manifest_sha256": benchmark_hash,
                "temperature": 0.0,
                "infra_excluded": 0,
                "mean_score": sum(1.0 if index in successes else 0.2 for index in range(51)) / 51,
                "tool_calls": {"mean": 2.0},
                "latency_seconds": {"mean": 1.0},
            }
        ),
        encoding="utf-8",
    )
    return path


def test_open_only_comparison_reports_directional_positive(tmp_path: Path) -> None:
    base = _run(tmp_path / "base", successes={0, 1})
    mixed = _run(tmp_path / "mixed", successes={0})
    open_only = _run(tmp_path / "open", successes={0, 1, 2, 3})

    result = compare(base, mixed, open_only, seed=7, control_audit={"status": "PASS"})

    assert result["status"] == "PASS"
    assert result["conclusion"] == "OPEN_ONLY_DIRECTION_POSITIVE"
    assert result["pairwise"]["open_vs_mixed"]["wins"] == 3
    assert result["pairwise"]["open_vs_mixed"]["losses"] == 0
    assert result["runs"]["open_only"]["behavior"]["search_to_read_conversion_rate"] == 1.0
    assert result["runs"]["open_only"]["behavior"]["successful_evidence_gain_steps"] == 102


def test_open_only_comparison_fails_closed_on_benchmark_drift(tmp_path: Path) -> None:
    base = _run(tmp_path / "base", successes={0})
    mixed = _run(tmp_path / "mixed", successes={0}, benchmark_hash="other")
    open_only = _run(tmp_path / "open", successes={0, 1})

    result = compare(base, mixed, open_only, seed=7, control_audit={"status": "PASS"})

    assert result["status"] == "FAIL"
    assert "benchmark_hash_mismatch" in result["failures"]


def test_open_only_comparison_blocks_promotion_when_training_control_failed(
    tmp_path: Path,
) -> None:
    base = _run(tmp_path / "base", successes={0, 1})
    mixed = _run(tmp_path / "mixed", successes={0})
    open_only = _run(tmp_path / "open", successes={0, 1, 2, 3})

    result = compare(
        base,
        mixed,
        open_only,
        seed=7,
        control_audit={"status": "FAIL", "failures": ["lr_schedule_mismatches"]},
    )

    assert result["status"] == "FAIL"
    assert result["conclusion"] == "CONTROL_CONTRACT_FAILED_LR_SCHEDULE"
    assert result["diagnostic_conclusion"] == "OPEN_ONLY_DIRECTION_POSITIVE"
    assert result["directional_gates"]["diagnostic_status"] == "PASS"
    assert result["directional_gates"]["status"] == "FAIL"


def test_open_only_comparison_cli_is_directly_executable() -> None:
    script = Path(__file__).resolve().parents[3] / "scripts/train/compare_open_only_sft_dev.py"

    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "--open-run" in result.stdout
    assert "--control-audit" in result.stdout
