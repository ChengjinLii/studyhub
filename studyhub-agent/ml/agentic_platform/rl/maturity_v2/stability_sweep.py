"""Validation-only long-horizon stabilization sweep for formal Router GRPO."""

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
OUTPUT_ROOT = ARTIFACT_ROOT / "experiments/grpo_stability_sweep"
EVALUATION_ROOT = (
    ROOT
    / "evaluation_artifacts/studyhub_agent/router_rl_maturity_v2/validation/grpo_stability_sweep"
)
BASELINE_PATH = (
    ROOT
    / "evaluation_artifacts/studyhub_agent/router_rl_maturity_v2/validation/baseline_sft/summary.json"
)
SEED = 26_081_231
TRIALS: tuple[tuple[str, dict[str, Any]], ...] = (
    (
        "mix12_constant_control",
        {
            "rollout_updates": 20,
            "learning_rate_schedule": "constant",
            "learning_rate_decay_optimizer_updates": 40,
            "learning_rate_min_ratio": 1.0,
            "formal_eligible": False,
        },
    ),
    (
        "cosine_decay40",
        {
            "learning_rate_schedule": "cosine",
            "learning_rate_decay_optimizer_updates": 40,
            "learning_rate_min_ratio": 0.02,
        },
    ),
    (
        "cosine_decay80",
        {
            "learning_rate_schedule": "cosine",
            "learning_rate_decay_optimizer_updates": 80,
            "learning_rate_min_ratio": 0.02,
        },
    ),
    (
        "cosine_decay120",
        {
            "learning_rate_schedule": "cosine",
            "learning_rate_decay_optimizer_updates": 120,
            "learning_rate_min_ratio": 0.02,
        },
    ),
    (
        "lr5e6_cosine80",
        {
            "learning_rate": 5e-6,
            "learning_rate_schedule": "cosine",
            "learning_rate_decay_optimizer_updates": 80,
            "learning_rate_min_ratio": 0.02,
        },
    ),
    (
        "kl010_cosine80",
        {
            "reference_kl_beta": 0.10,
            "learning_rate_schedule": "cosine",
            "learning_rate_decay_optimizer_updates": 80,
            "learning_rate_min_ratio": 0.02,
        },
    ),
    (
        "linear_decay80",
        {
            "learning_rate_schedule": "linear",
            "learning_rate_decay_optimizer_updates": 80,
            "learning_rate_min_ratio": 0.02,
        },
    ),
)


def prepare_stability_sweep(
    *,
    primary_results_path: Path,
    failed_scale_results_path: Path,
    output_dir: Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"refusing to overwrite stability sweep: {output_dir}")
    primary = _read_json(primary_results_path)
    failed_scale = _read_json(failed_scale_results_path)
    selected = primary["selected_config"]
    if failed_scale.get("gate_passed") is not False:
        raise ValueError("stability sweep requires a recorded failed scale Gate")
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
        "rollout_updates": 60,
        "group_size": 10,
        "material_episodes_per_update": 1,
        "boundary_episodes_per_update": 2,
        "policy_epochs": 2,
        "action_temperature": 1.25,
        "learning_rate": float(selected["learning_rate"]),
        "learning_rate_schedule": "cosine",
        "learning_rate_decay_optimizer_updates": 80,
        "learning_rate_min_ratio": 0.02,
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
    for index, (name, raw_overrides) in enumerate(TRIALS):
        overrides = dict(raw_overrides)
        formal_eligible = bool(overrides.pop("formal_eligible", True))
        config = {**base, **overrides}
        config["output_root"] = str((output_dir / "runs" / name).resolve())
        config_path = configs_dir / f"{index:02d}_{name}.json"
        _write_json(config_path, config)
        rows.append(
            {
                "index": index,
                "name": name,
                "overrides": overrides,
                "formal_eligible": formal_eligible,
                "config_path": str(config_path.resolve()),
                "config_sha256": sha256_file(config_path),
                "seed": SEED,
                "shard": index % 2,
            }
        )
    manifest = {
        "schema_version": "studyhub.agent.router_rl.grpo_stability_sweep.v2",
        "status": "prepared_after_failed_scale_gate",
        "primary_results_path": str(primary_results_path.resolve()),
        "primary_results_sha256": sha256_file(primary_results_path),
        "failed_scale_results_path": str(failed_scale_results_path.resolve()),
        "failed_scale_results_sha256": sha256_file(failed_scale_results_path),
        "trials": rows,
        "selection_split": "validation",
        "test_read": False,
        "sealed_read": False,
        "production_access": False,
    }
    _write_json(output_dir / "sweep_manifest.json", manifest)
    return manifest


def summarize_stability_sweep(
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
        formal_rollouts = (
            500
            * int(config["group_size"])
            * (
                int(config["material_episodes_per_update"])
                + int(config["boundary_episodes_per_update"])
            )
        )
        formal_eligible = bool(trial["formal_eligible"]) and formal_rollouts >= 10_000
        rows.append(
            {
                "name": trial["name"],
                "formal_eligible": formal_eligible,
                "formal_planned_trajectory_rollouts": formal_rollouts,
                "config": {
                    key: config[key]
                    for key in (
                        "lora_rank",
                        "learning_rate",
                        "learning_rate_schedule",
                        "learning_rate_decay_optimizer_updates",
                        "learning_rate_min_ratio",
                        "reference_kl_beta",
                        "trajectory_discount",
                        "group_size",
                        "material_episodes_per_update",
                        "boundary_episodes_per_update",
                        "entropy_beta",
                        "action_temperature",
                    )
                },
                "training": {
                    "rollout_updates": training["rollout_updates"],
                    "optimizer_updates": training["optimizer_updates"],
                    "trajectory_rollouts": training["trajectory_rollouts"],
                    "mean_reference_kl": training["stability"]["mean_reference_kl"],
                    "initial_learning_rate": training["stability"][
                        "initial_learning_rate"
                    ],
                    "final_learning_rate": training["stability"]["final_learning_rate"],
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
                "validation_gate": validation_gate,
                "rank_key": list(screen_rank_key(evaluation, baseline)),
                "training_summary_path": str((run_dir / "run_summary.json").resolve()),
                "evaluation_summary_path": str(evaluation_path.resolve()),
            }
        )
    passing = [
        row
        for row in rows
        if row["formal_eligible"] and row["validation_gate"]["passed"]
    ]
    selected = max(passing, key=lambda row: tuple(row["rank_key"])) if passing else None
    result = {
        "schema_version": "studyhub.agent.router_rl.grpo_stability_sweep_results.v2",
        "gate_passed": selected is not None,
        "trials": rows,
        "selected_trial": selected["name"] if selected else None,
        "selected_config": selected["config"] if selected else None,
        "required_mixture_control_compared": any(
            row["name"] == "mix12_constant_control" for row in rows
        ),
        "required_decay_horizons_compared": {40, 80, 120}.issubset(
            {
                int(row["config"]["learning_rate_decay_optimizer_updates"])
                for row in rows
            }
        ),
        "required_schedule_shapes_compared": {"constant", "linear", "cosine"}.issubset(
            {str(row["config"]["learning_rate_schedule"]) for row in rows}
        ),
        "test_read": False,
        "sealed_read": False,
        "production_access": False,
    }
    _write_json(evaluation_root / "stability_sweep_results.json", result)
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
    prepare.add_argument("--primary-results", type=Path, required=True)
    prepare.add_argument("--failed-scale-results", type=Path, required=True)
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
        result: Any = prepare_stability_sweep(
            primary_results_path=args.primary_results.resolve(),
            failed_scale_results_path=args.failed_scale_results.resolve(),
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
        result = summarize_stability_sweep(
            manifest_path=args.manifest.resolve(),
            evaluation_root=args.evaluation_root.resolve(),
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
