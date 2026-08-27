import json
from pathlib import Path

import pytest

from scripts.train.promote_runtime_sft_profiles import build_comparison


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def make_profile(root: Path, label: str, rank: int, *, token_delta: int = 0) -> tuple[Path, Path]:
    trial = f"profile-{label}-seed-20260827-test"
    evidence = root / label / "evidence"
    log = root / label / "run.log"
    gpu = root / label / "gpu.csv"
    run_path = root / label / "run.json"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("healthy", encoding="utf-8")
    gpu.write_text("healthy", encoding="utf-8")
    run = {
        "run_mode": f"runtime-sft-v3-9b-profile-{label}",
        "exit_status": 0,
        "started_at": "2026-08-27T00:00:00+08:00",
        "finished_at": "2026-08-27T00:01:00+08:00",
        "git": {"commit": "abc", "branch": "main", "status": ""},
        "config": {
            "sha256": "config",
            "overrides": [
                "seed=20260827",
                f"trial_name={trial}",
                "total_train_steps=5",
                f"actor.lora_rank={rank}",
                f"actor.lora_alpha={rank}",
            ],
        },
        "model": {
            "config_sha256": "model-config",
            "weight_files": [{"sha256": "weight"}],
        },
        "dataset_manifest_sha256": "dataset",
        "dataset_manifest": {"benchmark_lock": {"benchmark_manifest_sha256": "benchmark"}},
        "data_card": {"sha256": "card"},
        "dataset_release": {
            "release_status": "ACCEPTED_FOR_SFT_GATE",
            "final_audit_status": "PASS",
        },
        "resource_guard": {"max_used_mib": 72000},
        "log_file": str(log),
        "gpu_csv": str(gpu),
    }
    write_json(run_path, run)
    write_json(evidence / "manifest.json", {"trial": trial})
    write_json(evidence / "artifact-completeness.json", {"status": "COMPLETE"})
    summary = {
        name: {"count": 5, "first": value, "last": value, "min": value, "max": value, "mean": value}
        for name, value in {
            "sft/update_successful": 1.0,
            "sft/loss/avg": 0.5,
            "sft/ppl/avg": 1.65,
            "sft/grad_norm": 0.4,
            "sft/entropy/avg": 0.28,
            "sft/n_seqs": 8.0,
            "sft/n_tokens": 10000.0 + token_delta,
            "sft/n_valid_tokens": 1400.0,
            "timeperf/train_step": 10.0 if rank == 16 else 10.5,
        }.items()
    }
    write_json(evidence / "metrics/trainer.json", {"summary": summary})
    write_json(
        evidence / "metrics/system.json",
        {
            "per_gpu": {
                "0": {"peak_memory_used_mib": 60000.0},
                "1": {"peak_memory_used_mib": 50000.0},
            }
        },
    )
    write_json(
        evidence / "metrics/lora-immutability.json",
        {
            "update_observed": True,
            "initial": {"sha256": f"{label}-initial"},
            "final": {"sha256": f"{label}-final", "bytes": rank * 1000},
        },
    )
    (evidence / "SHA256SUMS").write_text("hashes", encoding="utf-8")
    return run_path, evidence


def test_profiles_require_equal_budget_and_select_lower_cost_default(tmp_path: Path) -> None:
    r16_run, r16_evidence = make_profile(tmp_path, "r16", 16)
    r32_run, r32_evidence = make_profile(tmp_path, "r32", 32)
    output = tmp_path / "profile.json"

    record = build_comparison(
        r16_run=r16_run,
        r16_evidence=r16_evidence,
        r32_run=r32_run,
        r32_evidence=r32_evidence,
        output=output,
    )

    assert record["status"] == "PASSED"
    assert record["comparison"]["selected_engineering_recipe"] == "r16"
    assert record["comparison"]["quality_claim"] == "NOT_EVALUATED_BY_PROFILE"
    assert output.is_file()


def test_profiles_fail_closed_on_actual_token_budget_mismatch(tmp_path: Path) -> None:
    r16_run, r16_evidence = make_profile(tmp_path, "r16", 16)
    r32_run, r32_evidence = make_profile(tmp_path, "r32", 32, token_delta=1)

    with pytest.raises(RuntimeError, match="tokens_budget_mismatch"):
        build_comparison(
            r16_run=r16_run,
            r16_evidence=r16_evidence,
            r32_run=r32_run,
            r32_evidence=r32_evidence,
            output=tmp_path / "profile.json",
        )
