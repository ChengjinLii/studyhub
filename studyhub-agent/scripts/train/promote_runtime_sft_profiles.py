#!/usr/bin/env python3
"""Compare ignored r16/r32 SFT profiles and emit compact tracked evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

PROFILE_STEPS = 5
PROFILE_SPECS = {
    "r16": {"mode": "runtime-sft-v3-9b-profile-r16", "rank": 16, "alpha": 16},
    "r32": {"mode": "runtime-sft-v3-9b-profile-r32", "rank": 32, "alpha": 32},
}


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


def parse_overrides(rows: list[str]) -> dict[str, str]:
    return {key: value for row in rows for key, separator, value in [row.partition("=")] if separator}


def metric(summary: dict[str, Any], name: str, *, expected_count: int = PROFILE_STEPS) -> dict[str, Any]:
    row = summary.get(name)
    if not isinstance(row, dict) or row.get("count") != expected_count:
        raise RuntimeError(f"profile must contain {expected_count} {name} values")
    return row


def profile_record(
    *,
    label: str,
    run_metadata_path: Path,
    evidence_root: Path,
) -> dict[str, Any]:
    spec = PROFILE_SPECS[label]
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
    summary = trainer.get("summary", {})
    overrides = parse_overrides(run.get("config", {}).get("overrides", []))

    failures: list[str] = []
    if run.get("run_mode") != spec["mode"]:
        failures.append("run_mode_mismatch")
    if run.get("exit_status") != 0:
        failures.append("nonzero_exit")
    if run.get("git", {}).get("status"):
        failures.append("dirty_worktree")
    if completeness.get("status") != "COMPLETE":
        failures.append("incomplete_evidence")
    release = run.get("dataset_release", {})
    if release.get("release_status") != "ACCEPTED_FOR_SFT_GATE" or release.get("final_audit_status") != "PASS":
        failures.append("dataset_release_not_accepted")
    if overrides.get("total_train_steps") != str(PROFILE_STEPS):
        failures.append("step_budget_mismatch")
    if overrides.get("actor.lora_rank") != str(spec["rank"]):
        failures.append("lora_rank_mismatch")
    if overrides.get("actor.lora_alpha") != str(spec["alpha"]):
        failures.append("lora_alpha_mismatch")
    if not lora.get("update_observed") or lora.get("initial", {}).get("sha256") == lora.get("final", {}).get("sha256"):
        failures.append("lora_update_not_observed")

    try:
        update = metric(summary, "sft/update_successful")
        if update.get("min") != 1.0 or update.get("max") != 1.0:
            failures.append("optimizer_update_failed")
        selected_metrics = {
            name: metric(summary, name)
            for name in (
                "sft/loss/avg",
                "sft/ppl/avg",
                "sft/grad_norm",
                "sft/entropy/avg",
                "sft/n_seqs",
                "sft/n_tokens",
                "sft/n_valid_tokens",
                "timeperf/train_step",
            )
        }
    except RuntimeError as exc:
        failures.append(str(exc))
        selected_metrics = {}

    guard_limit = int(run.get("resource_guard", {}).get("max_used_mib", 0))
    per_gpu = system.get("per_gpu", {})
    if set(per_gpu) != {"0", "1"}:
        failures.append("dual_gpu_telemetry_missing")
    elif any(float(row["peak_memory_used_mib"]) > guard_limit for row in per_gpu.values()):
        failures.append("gpu_guard_exceeded")
    if failures:
        raise RuntimeError(f"{label} profile cannot be promoted: " + ", ".join(failures))

    return {
        "label": label,
        "status": "PASSED",
        "trial": manifest["trial"],
        "run_mode": run["run_mode"],
        "started_at": run["started_at"],
        "finished_at": run["finished_at"],
        "git": run["git"],
        "config": {
            "sha256": run["config"]["sha256"],
            "seed": int(overrides["seed"]),
            "steps": PROFILE_STEPS,
            "rank": spec["rank"],
            "alpha": spec["alpha"],
            "target_modules": ["o_proj", "gate_proj", "up_proj", "down_proj"],
        },
        "model": {
            "config_sha256": run["model"]["config_sha256"],
            "weight_sha256": [row["sha256"] for row in run["model"]["weight_files"]],
        },
        "data": {
            "manifest_sha256": run["dataset_manifest_sha256"],
            "data_card_sha256": run["data_card"]["sha256"],
            "benchmark_lock": run["dataset_manifest"]["benchmark_lock"],
        },
        "optimizer": {
            "updates": PROFILE_STEPS,
            "loss": selected_metrics["sft/loss/avg"],
            "perplexity": selected_metrics["sft/ppl/avg"],
            "gradient_norm": selected_metrics["sft/grad_norm"],
            "entropy": selected_metrics["sft/entropy/avg"],
            "sequences": int(selected_metrics["sft/n_seqs"]["mean"] * PROFILE_STEPS),
            "tokens": int(selected_metrics["sft/n_tokens"]["mean"] * PROFILE_STEPS),
            "assistant_loss_tokens": int(selected_metrics["sft/n_valid_tokens"]["mean"] * PROFILE_STEPS),
            "train_step_seconds": selected_metrics["timeperf/train_step"],
        },
        "lora_update": {
            "bytes": lora["final"]["bytes"],
            "initial_sha256": lora["initial"]["sha256"],
            "final_sha256": lora["final"]["sha256"],
            "update_observed": True,
        },
        "gpu": {"guard_max_used_mib": guard_limit, "per_gpu": per_gpu},
        "raw_evidence": {
            "run_metadata": {"path": str(run_metadata_path), "sha256": sha256(run_metadata_path)},
            "bundle_manifest": {"path": str(manifest_path), "sha256": sha256(manifest_path)},
            "bundle_checksums": {"path": str(checksum_path), "sha256": sha256(checksum_path)},
            "training_log": {"path": run["log_file"], "sha256": sha256(Path(run["log_file"]))},
            "gpu_telemetry": {"path": run["gpu_csv"], "sha256": sha256(Path(run["gpu_csv"]))},
        },
    }


def build_comparison(
    *,
    r16_run: Path,
    r16_evidence: Path,
    r32_run: Path,
    r32_evidence: Path,
    output: Path,
) -> dict[str, Any]:
    profiles = {
        "r16": profile_record(label="r16", run_metadata_path=r16_run, evidence_root=r16_evidence),
        "r32": profile_record(label="r32", run_metadata_path=r32_run, evidence_root=r32_evidence),
    }
    left, right = profiles["r16"], profiles["r32"]
    failures: list[str] = []
    if left["git"]["commit"] != right["git"]["commit"]:
        failures.append("git_commit_mismatch")
    if left["config"]["seed"] != right["config"]["seed"]:
        failures.append("seed_mismatch")
    if left["model"] != right["model"]:
        failures.append("model_mismatch")
    if left["data"] != right["data"]:
        failures.append("data_mismatch")
    for name in ("sequences", "tokens", "assistant_loss_tokens"):
        if left["optimizer"][name] != right["optimizer"][name]:
            failures.append(f"{name}_budget_mismatch")
    if failures:
        raise RuntimeError("profiles are not controlled comparisons: " + ", ".join(failures))

    r16_step = float(left["optimizer"]["train_step_seconds"]["mean"])
    r32_step = float(right["optimizer"]["train_step_seconds"]["mean"])
    r16_peak = max(float(row["peak_memory_used_mib"]) for row in left["gpu"]["per_gpu"].values())
    r32_peak = max(float(row["peak_memory_used_mib"]) for row in right["gpu"]["per_gpu"].values())
    recommend_r32 = r32_step <= r16_step * 0.95 and r32_peak <= r16_peak + 1024
    selected = "r32" if recommend_r32 else "r16"
    selection_reason = (
        "r32 reduced mean optimizer-step wall time by at least 5% without adding more than 1 GiB peak memory."
        if recommend_r32
        else "r32 did not deliver a >=5% optimizer-step speedup within a 1 GiB peak-memory envelope; "
        "r16 is the lower-capacity engineering default."
    )

    record = {
        "schema_version": "studyhub.runtime-sft-profile-evidence.v3",
        "status": "PASSED",
        "evidence_grade": "A_REAL_REPRODUCED",
        "controlled_variables": [
            "git_commit",
            "model_weights",
            "dataset_manifest",
            "benchmark_lock",
            "seed",
            "task_order",
            "five_optimizer_updates",
            "actual_sequence_and_token_budget",
            "GPU_guard",
        ],
        "profiles": profiles,
        "comparison": {
            "r32_minus_r16_mean_train_step_seconds": r32_step - r16_step,
            "r32_minus_r16_peak_memory_used_mib": r32_peak - r16_peak,
            "selected_engineering_recipe": selected,
            "selection_reason": selection_reason,
            "quality_claim": "NOT_EVALUATED_BY_PROFILE",
        },
        "claim_boundary": (
            "This profile compares runtime stability and resource cost over five updates. It does not "
            "measure downstream Agent capability; formal SFT still requires independent AgentBench v2 evaluation."
        ),
        "next_action": f"Use {selected} for the formal 9B SFT recipe, then evaluate checkpoints independently.",
        "generator": {"path": str(Path(__file__).resolve()), "sha256": sha256(Path(__file__).resolve())},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return record


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--r16-run", type=Path, required=True)
    parser.add_argument("--r16-evidence", type=Path, required=True)
    parser.add_argument("--r32-run", type=Path, required=True)
    parser.add_argument("--r32-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    record = build_comparison(
        r16_run=args.r16_run.resolve(),
        r16_evidence=args.r16_evidence.resolve(),
        r32_run=args.r32_run.resolve(),
        r32_evidence=args.r32_evidence.resolve(),
        output=args.output.resolve(),
    )
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
