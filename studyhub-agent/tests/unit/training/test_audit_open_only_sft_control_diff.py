from __future__ import annotations

import json
from pathlib import Path

from scripts.train.audit_open_only_sft_control_diff import (
    add_control,
    classify_audit,
    parse_overrides,
    recovery_contract_status,
)


def test_parse_overrides_preserves_null_boolean_and_numeric_values() -> None:
    assert parse_overrides(
        [
            "total_train_steps=2100",
            "evaluator.freq_steps=null",
            "enabled=true",
            "lr=2e-5",
        ]
    ) == {
        "total_train_steps": 2100,
        "evaluator.freq_steps": None,
        "enabled": True,
        "lr": 2e-5,
    }


def test_control_difference_is_fail_closed_unless_declared_data_condition() -> None:
    rows = {}
    add_control(rows, "learning_rate", 2e-5, 3e-5)
    add_control(
        rows,
        "dataset_manifest",
        "mixed",
        "open",
        required_equal=False,
    )

    assert rows["learning_rate"]["status"] == "FAIL"
    assert rows["dataset_manifest"]["status"] == "PASS"
    assert rows["dataset_manifest"]["equal"] is False


def _write_recovery_evidence(path: Path, **overrides: object) -> None:
    payload = {
        "schema_version": "studyhub.sft-recovery-gate.v2",
        "status": "PASS",
        "scope": {
            "formal_training_eligible": True,
            "boundary": "POST_WARMUP",
            "rl_started": False,
            "sealed_used": False,
        },
        "gates": {
            "R1_lr_schedule": {"status": "PASS"},
            "R2_snapshot_integrity": {"status": "PASS"},
            "R3_state_continuity": {"status": "PASS"},
            "R4_final_equivalence": {"status": "BITWISE_RESUME_PASS"},
        },
    }
    payload.update(overrides)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_recovery_evidence_requires_all_four_formal_gates(tmp_path: Path) -> None:
    evidence = tmp_path / "recovery.json"
    _write_recovery_evidence(evidence)

    result = recovery_contract_status(evidence)

    assert result["status"] == "PASS"
    assert result["eligible"] is True


def test_early_warmup_recovery_evidence_cannot_unblock_training(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "recovery.json"
    _write_recovery_evidence(
        evidence,
        scope={
            "formal_training_eligible": False,
            "boundary": "EARLY_WARMUP_MECHANICS_ONLY",
            "rl_started": False,
            "sealed_used": False,
        },
    )

    result = recovery_contract_status(evidence)

    assert result["status"] == "FAIL"
    assert result["eligible"] is False
    assert "recovery_boundary_not_formal_training_eligible" in result["failures"]


def test_any_model_affecting_control_drift_blocks_training() -> None:
    status, decision, blockers = classify_audit(
        hard_failures=["learning_rate"],
        provenance_failures=[],
        runtime_requires_confirmation=False,
        worktree_dirty=False,
    )

    assert status == "BLOCKED"
    assert decision == "BLOCKED_CONTROL_DRIFT"
    assert blockers == ["MODEL_AFFECTING_CONTROL_DRIFT"]


def test_only_unconfirmed_runtime_correction_reports_recovery_blocker() -> None:
    status, decision, blockers = classify_audit(
        hard_failures=[],
        provenance_failures=[],
        runtime_requires_confirmation=True,
        worktree_dirty=False,
    )

    assert status == "BLOCKED"
    assert decision == "BLOCKED_RECOVERY_CONTRACT"
    assert blockers == ["RUNTIME_CORRECTIONS_REQUIRE_R1_R4_CONFIRMATION"]
