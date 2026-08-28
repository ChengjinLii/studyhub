from __future__ import annotations

import hashlib
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_recovery_ready_evidence_is_bound_to_current_inputs() -> None:
    evidence = json.loads(
        (
            PROJECT_ROOT
            / "docs/training/evidence/open-only-sft-v1-1-recovery-ready-not-run-20260828.json"
        ).read_text(encoding="utf-8")
    )
    paths = {
        "launcher": "scripts/train/run_open_only_sft_v1_1_recovery_gate.sh",
        "snapshot": "scripts/train/snapshot_sft_recovery_prefix.py",
        "verifier": "scripts/train/verify_sft_recovery_gate.py",
        "recovery_state_bridge": "training/runtime_shims/areal_recovery_state_bridge.py",
        "scheduler_bridge": "training/runtime_shims/areal_scheduler_bridge.py",
        "config": "configs/train/open-only-sft-v1.1-qwen35-9b.yaml",
        "program": "configs/program-v3/open-only-sft-v1.1-lrmatched.json",
        "authorization": (
            "configs/program-v3/open-only-sft-v1.1-lrmatched-authorization.json"
        ),
        "equivalence_contract": (
            "configs/program-v3/sft-recovery-numerical-equivalence-v1.json"
        ),
        "dataset_manifest": (
            "datasets/processed/open_only_sft_v1_qwen35_9b/manifest.json"
        ),
        "benchmark_manifest": "benchmarks/studyhub-agent-v2/manifest.json",
    }

    assert evidence["status"] == "READY_BUT_NOT_RUN"
    assert evidence["authorization"]["gpu_job_started"] is False
    for label, relative in paths.items():
        assert evidence["input_hashes"][label] == sha256(PROJECT_ROOT / relative)
