from __future__ import annotations

import json
from pathlib import Path

from scripts.train.compare_base_sft_dev import compare


def _run(root: Path, name: str, strict_successes: set[int]) -> Path:
    path = root / name
    path.mkdir()
    summary = {
        "mode": "development",
        "benchmark_manifest_sha256": "a" * 64,
        "temperature": 0.0,
        "infra_excluded": 0,
        "run_id": name,
        "model": name,
        "strict_success_rate": len(strict_successes) / 51,
        "mean_score": 0.5,
        "tool_calls": {"mean": 2.0},
        "latency_seconds": {"mean": 1.0},
        "approx_independent_mde_80_power_pp": 17.865,
    }
    (path / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    with (path / "episodes.jsonl").open("w", encoding="utf-8") as stream:
        for ordinal in range(51):
            stream.write(
                json.dumps(
                    {
                        "status": "SCORED",
                        "task_id": f"development-{ordinal:03d}",
                        "capability_id": f"family-{ordinal % 3}",
                        "evaluation": {
                            "strict_success": ordinal in strict_successes,
                            "diagnostic_scalar": 0.8 if ordinal in strict_successes else 0.2,
                            "tool_validity": 1.0,
                            "tool_calls": 2,
                            "hard_gate_reasons": [],
                            "diagnostics": {"sealed": False},
                        },
                        "trace": {"environment_errors": [], "policy_errors": [], "runtime_errors": []},
                    },
                    sort_keys=True,
                )
                + "\n"
            )
    return path


def test_compare_base_sft_dev_reports_paired_wins_without_sealed(tmp_path: Path) -> None:
    base = _run(tmp_path, "base", {0, 1, 2})
    sft = _run(tmp_path, "sft", {0, 1, 2, 3, 4})

    result = compare(base, sft, seed=17)

    assert result["status"] == "PASS"
    assert result["sealed_used"] is False
    assert result["paired_tasks"] == 51
    assert result["paired_strict"]["wins"] == 2
    assert result["paired_strict"]["losses"] == 0
    assert result["paired_strict"]["ties"] == 49
    assert result["claim"] == "DIRECTIONAL_PAIRED_EVIDENCE_ONLY"
