"""Scale-screen rollout group size and entropy before five-seed formal GRPO."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..spec import sha256_file
from .gate import (
    assess_validation_candidate,
    paired_bootstrap,
    screen_rank_key,
)
from .sweep import run_shard
from .sweep_evaluate import evaluate_shard
from .train_grpo import ALGORITHM, SCHEMA_VERSION

ROOT = Path(__file__).resolve().parents[4]
ARTIFACT_ROOT = ROOT / "training_artifacts/studyhub_agent_rl/router_rl_maturity_v2"
OUTPUT_ROOT = ARTIFACT_ROOT / "experiments/grpo_scale_sweep"
EVALUATION_ROOT = (
    ROOT
    / "evaluation_artifacts/studyhub_agent/router_rl_maturity_v2/validation/grpo_scale_sweep"
)
BASELINE_PATH = (
    ROOT
    / "evaluation_artifacts/studyhub_agent/router_rl_maturity_v2/validation/baseline_sft/summary.json"
)
SEED = 26_081_221
TRIALS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("group10_entropy0", {"group_size": 10, "entropy_beta": 0.0}),
    ("group20_entropy0", {"group_size": 20, "entropy_beta": 0.0}),
    ("group20_entropy002", {"group_size": 20, "entropy_beta": 0.002}),
    ("group20_entropy01", {"group_size": 20, "entropy_beta": 0.01}),
    (
        "group20_entropy002_temp15",
        {"group_size": 20, "entropy_beta": 0.002, "action_temperature": 1.5},
    ),
)


def prepare_scale_sweep(
    *,
    source_results_path: Path,
    output_dir: Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"refusing to overwrite scale sweep: {output_dir}")
    source = _read_json(source_results_path)
    selected = source["selected_config"]
    configs_dir = output_dir / "configs"
    configs_dir.mkdir(parents=True, exist_ok=True)
    base: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "algorithm": ALGORITHM,
        "model_path": str(
            (
                ROOT
                / "training_artifacts/studyhub_agent_sft/qwen35_2b_router_v1_7_merged"
            ).resolve()
        ),
        "train_path": str((ARTIFACT_ROOT / "train.jsonl").resolve()),
        "reference_cache_path": str(
            (ARTIFACT_ROOT / "reference/train_reference.jsonl").resolve()
        ),
        "lora_rank": int(selected["lora_rank"]),
        "lora_alpha": int(selected["lora_rank"]) * 2,
        "lora_dropout": 0.0,
        "rollout_updates": 20,
        "group_size": 20,
        "material_episodes_per_update": 1,
        "boundary_episodes_per_update": 1,
        "policy_epochs": 2,
        "action_temperature": 1.25,
        "learning_rate": float(selected["learning_rate"]),
        "adam_beta1": 0.9,
        "adam_beta2": 0.95,
        "weight_decay": 0.0,
        "reference_kl_beta": float(selected["reference_kl_beta"]),
        "clip_epsilon": 0.2,
        "entropy_beta": 0.0,
        "trajectory_discount": float(selected["trajectory_discount"]),
        "terminal_bonus": 0.4,
        "failure_penalty": 0.4,
        "max_grad_norm": 1.0,
        "max_prompt_tokens": 4096,
        "checkpoint_every": 20,
        "gradient_checkpointing": True,
        "device": "cuda:0",
        "formal_run": False,
        "isolation": {
            "production_access_allowed": False,
            "paid_material_allowed": False,
            "test_read_allowed": False,
            "sealed_read_allowed": False,
            "production_final_holdout_allowed": False,
        },
    }
    rows: list[dict[str, Any]] = []
    for index, (name, overrides) in enumerate(TRIALS):
        config = {**base, **overrides}
        config["output_root"] = str((output_dir / "runs" / name).resolve())
        config_path = configs_dir / f"{index:02d}_{name}.json"
        _write_json(config_path, config)
        rows.append(
            {
                "index": index,
                "name": name,
                "overrides": overrides,
                "config_path": str(config_path.resolve()),
                "config_sha256": sha256_file(config_path),
                "seed": SEED,
                "shard": index % 2,
            }
        )
    manifest = {
        "schema_version": "studyhub.agent.router_rl.grpo_scale_sweep.v2",
        "status": "prepared_after_primary_validation_screen",
        "source_results_path": str(source_results_path.resolve()),
        "source_results_sha256": sha256_file(source_results_path),
        "trials": rows,
        "selection_split": "validation",
        "test_read": False,
        "sealed_read": False,
        "production_access": False,
    }
    _write_json(output_dir / "sweep_manifest.json", manifest)
    return manifest


def summarize_scale_sweep(
    *,
    manifest_path: Path,
    evaluation_root: Path,
) -> dict[str, Any]:
    manifest = _read_json(manifest_path)
    baseline = _read_json(BASELINE_PATH)
    rows: list[dict[str, Any]] = []
    for trial in manifest["trials"]:
        config = _read_json(Path(trial["config_path"]))
        run_dir = Path(config["output_root"]) / f"seed_{trial['seed']}"
        training = _read_json(run_dir / "run_summary.json")
        evaluation_path = evaluation_root / trial["name"] / "summary.json"
        evaluation = _read_json(evaluation_path)
        statistics_result = paired_bootstrap(
            BASELINE_PATH.with_name("predictions.jsonl"),
            evaluation_path.with_name("predictions.jsonl"),
        )
        validation_gate = assess_validation_candidate(
            baseline=baseline,
            candidate=evaluation,
            statistics_result=statistics_result,
        )
        rows.append(
            {
                "name": trial["name"],
                "config": {
                    "lora_rank": config["lora_rank"],
                    "learning_rate": config["learning_rate"],
                    "reference_kl_beta": config["reference_kl_beta"],
                    "trajectory_discount": config["trajectory_discount"],
                    "group_size": config["group_size"],
                    "entropy_beta": config["entropy_beta"],
                    "action_temperature": config["action_temperature"],
                },
                "training": {
                    "trajectory_rollouts": training["trajectory_rollouts"],
                    "mean_nonzero_advantage_fraction": training["stability"][
                        "mean_nonzero_advantage_fraction"
                    ],
                    "mean_reference_kl": training["stability"]["mean_reference_kl"],
                    "peak_memory_mib": training["gpu"]["peak_memory_mib"],
                },
                "validation": {
                    "raw_reward": evaluation["raw"]["policy_reward_mean"],
                    "raw_choice_success": evaluation["raw"]["choice_success_rate"],
                    "raw_episode_success": evaluation["raw"]["episode_success_rate"],
                    "constraint_severity": evaluation["constraint"]["severity_mean"],
                    "raw_executable_choice_gap": evaluation["raw_executable"][
                        "choice_success_gap_absolute"
                    ],
                },
                "rank_key": list(screen_rank_key(evaluation, baseline)),
                "validation_gate": validation_gate,
                "training_summary_path": str((run_dir / "run_summary.json").resolve()),
                "evaluation_summary_path": str(evaluation_path.resolve()),
            }
        )
    best_screen = max(rows, key=lambda row: tuple(row["rank_key"]))
    passing = [row for row in rows if row["validation_gate"]["passed"]]
    selected = max(passing, key=lambda row: tuple(row["rank_key"])) if passing else None
    result = {
        "schema_version": "studyhub.agent.router_rl.grpo_scale_sweep_results.v2",
        "trials": rows,
        "gate_passed": selected is not None,
        "selected_trial": selected["name"] if selected else None,
        "selected_config": selected["config"] if selected else None,
        "best_screen_trial": best_screen["name"],
        "failure_blockers": (
            []
            if selected
            else sorted(
                {
                    blocker
                    for row in rows
                    for blocker in row["validation_gate"]["blockers"]
                }
            )
        ),
        "required_group_scale_compared": {10, 20}.issubset(
            {int(row["config"]["group_size"]) for row in rows}
        ),
        "required_entropy_scale_compared": {0.0, 0.002, 0.01}.issubset(
            {float(row["config"]["entropy_beta"]) for row in rows}
        ),
        "test_read": False,
        "sealed_read": False,
        "production_access": False,
    }
    _write_json(evaluation_root / "scale_sweep_results.json", result)
    return result


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--source-results", type=Path, required=True)
    prepare.add_argument("--output-dir", type=Path, default=OUTPUT_ROOT)
    run = subparsers.add_parser("run-shard")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--shard", type=int, choices=(0, 1), required=True)
    evaluate = subparsers.add_parser("evaluate-shard")
    evaluate.add_argument("--manifest", type=Path, required=True)
    evaluate.add_argument("--evaluation-root", type=Path, default=EVALUATION_ROOT)
    evaluate.add_argument("--shard", type=int, choices=(0, 1), required=True)
    evaluate.add_argument("--device", default="cuda:0")
    summarize = subparsers.add_parser("summarize")
    summarize.add_argument("--manifest", type=Path, required=True)
    summarize.add_argument("--evaluation-root", type=Path, default=EVALUATION_ROOT)
    args = parser.parse_args()
    if args.command == "prepare":
        result: Any = prepare_scale_sweep(
            source_results_path=args.source_results.resolve(),
            output_dir=args.output_dir.resolve(),
        )
    elif args.command == "run-shard":
        result = run_shard(manifest_path=args.manifest.resolve(), shard=args.shard)
    elif args.command == "evaluate-shard":
        result = evaluate_shard(
            manifest_path=args.manifest.resolve(),
            evaluation_root=args.evaluation_root.resolve(),
            shard=args.shard,
            device=args.device,
        )
    else:
        result = summarize_scale_sweep(
            manifest_path=args.manifest.resolve(),
            evaluation_root=args.evaluation_root.resolve(),
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
