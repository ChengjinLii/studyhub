from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/train/run_qwen35_4b_m1_evaluation_suite.py"
SPEC = importlib.util.spec_from_file_location("qwen35_4b_m1_evaluation_suite", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_stage_order_is_preregistered() -> None:
    assert MODULE.STAGES == ("merge", "protocol", "agentbench", "bfcl", "tau2")


def test_protocol_validation_requires_full_formal_pass() -> None:
    model = "StudyHub/qwen35-4b-sft1@example"
    valid = {
        "status": "PASS_SFT1_PROTOCOL_HOLDOUT",
        "formal_gate_evaluated": True,
        "model": model,
        "expected_items": 3022,
        "scored_items": 3022,
    }
    MODULE.validate_protocol(valid, model)
    with pytest.raises(RuntimeError, match="did not pass"):
        MODULE.validate_protocol({**valid, "status": "FAIL_SFT1_PROTOCOL_HOLDOUT"}, model)
    with pytest.raises(RuntimeError, match="3,022"):
        MODULE.validate_protocol({**valid, "scored_items": 3021}, model)


def test_capability_summaries_fail_closed_on_infra_or_partial_panels() -> None:
    model = "StudyHub/qwen35-4b-sft1@example"
    agentbench = {
        "schema_version": "studyhub.agentbench-run-summary.v2",
        "benchmark_version": "studyhub-agentbench-v2",
        "mode": "development",
        "episodes_expected": 51,
        "episodes_scored": 51,
        "infra_excluded": 0,
        "model": model,
    }
    MODULE.validate_agentbench(agentbench, model)
    with pytest.raises(RuntimeError, match="completeness"):
        MODULE.validate_agentbench({**agentbench, "infra_excluded": 1}, model)

    bfcl = {
        "status": "COMPLETED_BFCL_PUBLIC_PARTIAL_REPLICATION",
        "model": model,
        "scores": {"total_count": 70, "official_full_leaderboard_score": False},
    }
    MODULE.validate_bfcl(bfcl, model)
    with pytest.raises(RuntimeError, match="case count"):
        MODULE.validate_bfcl({**bfcl, "scores": {**bfcl["scores"], "total_count": 69}}, model)

    tau2 = {
        "status": "COMPLETED_TAU2_PUBLIC_PARTIAL_REPLICATION",
        "model": model,
        "scores": {"tasks": 15, "official_full_leaderboard_score": False},
    }
    MODULE.validate_tau2(tau2, model)
    with pytest.raises(RuntimeError, match="task count"):
        MODULE.validate_tau2({**tau2, "scores": {**tau2["scores"], "tasks": 14}}, model)


def test_receipt_detects_artifact_hash_drift(tmp_path: Path) -> None:
    model = "StudyHub/qwen35-4b-sft1@example"
    summary = tmp_path / "summary.json"
    summary.write_text(
        json.dumps(
            {
                "status": "COMPLETED_TAU2_PUBLIC_PARTIAL_REPLICATION",
                "model": model,
                "scores": {"tasks": 15, "official_full_leaderboard_score": False},
            }
        ),
        encoding="utf-8",
    )
    state = tmp_path / "state"
    state.mkdir()
    receipt = state / "tau2.json"
    receipt.write_text(
        json.dumps(
            {
                "status": "COMPLETE",
                "stage": "tau2",
                "model": model,
                "artifact": str(summary),
                "artifact_sha256": MODULE.sha256(summary),
            }
        ),
        encoding="utf-8",
    )
    assert MODULE.validate_receipt(state, "tau2", MODULE.validate_tau2, model)
    summary.write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="drifted"):
        MODULE.validate_receipt(state, "tau2", MODULE.validate_tau2, model)
