#!/usr/bin/env python3
"""Promote one ignored runtime SFT Gate into a compact tracked evidence record."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def one_metric(summary: dict[str, Any], name: str) -> float:
    row = summary.get(name)
    if not isinstance(row, dict) or row.get("count") != 1:
        raise RuntimeError(f"Gate must contain exactly one {name} value")
    return float(row["last"])


def build_record(
    *,
    run_metadata_path: Path,
    evidence_root: Path,
    output: Path,
) -> dict[str, Any]:
    run = load_json(run_metadata_path)
    manifest_path = evidence_root / "manifest.json"
    completeness_path = evidence_root / "artifact-completeness.json"
    trainer_path = evidence_root / "metrics/trainer.json"
    system_path = evidence_root / "metrics/system.json"
    lora_path = evidence_root / "metrics/lora-immutability.json"
    checksum_path = evidence_root / "SHA256SUMS"
    manifest = load_json(manifest_path)
    completeness = load_json(completeness_path)
    trainer = load_json(trainer_path)
    system = load_json(system_path)
    lora = load_json(lora_path)

    release = run.get("dataset_release", {})
    failures = []
    if run.get("exit_status") != 0:
        failures.append("nonzero_exit")
    if completeness.get("status") != "COMPLETE":
        failures.append("incomplete_evidence")
    if release.get("release_status") != "ACCEPTED_FOR_SFT_GATE":
        failures.append("dataset_not_accepted")
    if release.get("final_audit_status") != "PASS":
        failures.append("dataset_audit_not_passed")
    if not lora.get("update_observed"):
        failures.append("lora_update_not_observed")
    if one_metric(trainer["summary"], "sft/update_successful") != 1.0:
        failures.append("optimizer_update_failed")
    guard_limit = int(run["resource_guard"]["max_used_mib"])
    per_gpu = system.get("per_gpu", {})
    if set(per_gpu) != {"0", "1"}:
        failures.append("dual_gpu_telemetry_missing")
    if any(float(row["peak_memory_used_mib"]) > guard_limit for row in per_gpu.values()):
        failures.append("gpu_guard_exceeded")
    if failures:
        raise RuntimeError("Gate evidence cannot be promoted: " + ", ".join(failures))

    record = {
        "schema_version": "studyhub.runtime-sft-gate-evidence.v3",
        "status": "PASSED",
        "evidence_grade": "A_REAL_REPRODUCED",
        "trial": manifest["trial"],
        "run_mode": run["run_mode"],
        "started_at": run["started_at"],
        "finished_at": run["finished_at"],
        "git": run["git"],
        "model": {
            "path": run["model"]["path"],
            "revision": run["data_card"]["content"]["tokenization"]["local_revision"],
            "weight_sha256": [row["sha256"] for row in run["model"]["weight_files"]],
        },
        "dataset_release": release,
        "benchmark_lock": run["dataset_manifest"]["benchmark_lock"],
        "recipe": {
            "backend": "fsdp:d2p1t1",
            "gpus": 2,
            "dtype": "bfloat16",
            "lora_rank": 16,
            "lora_alpha": 16,
            "target_modules": ["o_proj", "gate_proj", "up_proj", "down_proj"],
            "global_batch_size": 8,
            "steps": 1,
            "learning_rate": one_metric(trainer["summary"], "sft/lr"),
            "loss_contract": run["data_card"]["content"]["tokenization"]["loss_contract"],
        },
        "optimizer_step": {
            "loss": one_metric(trainer["summary"], "sft/loss/avg"),
            "perplexity": one_metric(trainer["summary"], "sft/ppl/avg"),
            "gradient_norm": one_metric(trainer["summary"], "sft/grad_norm"),
            "entropy": one_metric(trainer["summary"], "sft/entropy/avg"),
            "sequences": int(one_metric(trainer["summary"], "sft/n_seqs")),
            "tokens": int(one_metric(trainer["summary"], "sft/n_tokens")),
            "assistant_loss_tokens": int(one_metric(trainer["summary"], "sft/n_valid_tokens")),
            "train_step_seconds": one_metric(trainer["summary"], "timeperf/train_step"),
            "checkpoint_save_seconds": one_metric(trainer["summary"], "timeperf/save"),
        },
        "lora_update": {
            "initial_sha256": lora["initial"]["sha256"],
            "final_sha256": lora["final"]["sha256"],
            "bytes": lora["final"]["bytes"],
            "update_observed": True,
        },
        "gpu": {
            "guard_max_used_mib": guard_limit,
            "per_gpu": per_gpu,
        },
        "raw_evidence": {
            "run_metadata": {"path": str(run_metadata_path), "sha256": sha256(run_metadata_path)},
            "bundle_manifest": {"path": str(manifest_path), "sha256": sha256(manifest_path)},
            "bundle_checksums": {"path": str(checksum_path), "sha256": sha256(checksum_path)},
            "training_log": {
                "path": run["log_file"],
                "sha256": sha256(Path(run["log_file"])),
            },
            "gpu_telemetry": {
                "path": run["gpu_csv"],
                "sha256": sha256(Path(run["gpu_csv"])),
            },
        },
        "claim_boundary": (
            "This Gate proves one guarded dual-H100 AReaL SFT optimizer update, "
            "checkpoint export, and evidence capture. It does not establish SFT quality, "
            "generalization, or promotion to RL."
        ),
        "next_action": "Run equal-budget r16 and r32 profiles before selecting the formal SFT recipe.",
        "generator": {
            "path": str(Path(__file__).resolve()),
            "sha256": sha256(Path(__file__).resolve()),
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return record


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-metadata", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    record = build_record(
        run_metadata_path=args.run_metadata.resolve(),
        evidence_root=args.evidence_root.resolve(),
        output=args.output.resolve(),
    )
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
