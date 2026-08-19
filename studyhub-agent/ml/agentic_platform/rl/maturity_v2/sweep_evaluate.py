"""Evaluate and summarize the GRPO maturity-v2 screen on Validation only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .evaluate import evaluate_policy
from .gate import screen_rank_key

ROOT = Path(__file__).resolve().parents[4]
DEFAULT_MANIFEST = (
    ROOT
    / "training_artifacts/studyhub_agent_rl/router_rl_maturity_v2/experiments/grpo_sweep/sweep_manifest.json"
)
DEFAULT_EVALUATION_ROOT = (
    ROOT / "evaluation_artifacts/studyhub_agent/router_rl_maturity_v2/validation/grpo_sweep"
)
BASELINE_SUMMARY = (
    ROOT
    / "evaluation_artifacts/studyhub_agent/router_rl_maturity_v2/validation/baseline_sft/summary.json"
)
VALIDATION_PATH = (
    ROOT / "training_artifacts/studyhub_agent_rl/router_rl_maturity_v2/validation.jsonl"
)
MODEL_PATH = (
    ROOT / "training_artifacts/studyhub_agent_sft/qwen35_2b_router_v1_7_merged"
)


def evaluate_shard(
    *,
    manifest_path: Path,
    evaluation_root: Path,
    shard: int,
    device: str,
) -> list[dict[str, Any]]:
    manifest = _read_json(manifest_path)
    results: list[dict[str, Any]] = []
    for trial in manifest["trials"]:
        if int(trial["shard"]) != shard:
            continue
        config = _read_json(Path(trial["config_path"]))
        run_dir = Path(config["output_root"]) / f"seed_{int(trial['seed'])}"
        adapter_path = run_dir / "adapter"
        if not (run_dir / "run_summary.json").is_file() or not adapter_path.is_dir():
            raise RuntimeError(f"sweep training is incomplete: {run_dir}")
        output_dir = evaluation_root / str(trial["name"])
        summary_path = output_dir / "summary.json"
        if summary_path.is_file():
            results.append(_read_json(summary_path))
            continue
        results.append(
            evaluate_policy(
                model_path=MODEL_PATH,
                adapter_path=adapter_path,
                dataset_path=VALIDATION_PATH,
                split="validation",
                output_dir=output_dir,
                device=device,
                max_prompt_tokens=4096,
                action_temperature=1.0,
                seed=26_081_201,
            )
        )
    return results


def summarize_sweep(
    *,
    manifest_path: Path,
    evaluation_root: Path,
) -> dict[str, Any]:
    manifest = _read_json(manifest_path)
    baseline = _read_json(BASELINE_SUMMARY)
    rows: list[dict[str, Any]] = []
    for trial in manifest["trials"]:
        config = _read_json(Path(trial["config_path"]))
        run_dir = Path(config["output_root"]) / f"seed_{int(trial['seed'])}"
        training = _read_json(run_dir / "run_summary.json")
        evaluation = _read_json(evaluation_root / str(trial["name"]) / "summary.json")
        rows.append(
            {
                "name": trial["name"],
                "index": trial["index"],
                "overrides": trial["overrides"],
                "config": {
                    "lora_rank": config["lora_rank"],
                    "learning_rate": config["learning_rate"],
                    "reference_kl_beta": config["reference_kl_beta"],
                    "group_size": config["group_size"],
                    "trajectory_discount": config["trajectory_discount"],
                },
                "training": {
                    "trajectory_rollouts": training["trajectory_rollouts"],
                    "action_rollouts": training["action_rollouts"],
                    "trajectory_success_rate": training["trajectory_success_rate"],
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
                    "family_floor": min(
                        value["choice_success_rate"]
                        for value in evaluation["raw"]["families"].values()
                    ),
                    "constraint_severity": evaluation["constraint"]["severity_mean"],
                    "raw_executable_choice_gap": evaluation["raw_executable"][
                        "choice_success_gap_absolute"
                    ],
                },
                "rank_key": list(screen_rank_key(evaluation, baseline)),
                "training_summary_path": str((run_dir / "run_summary.json").resolve()),
                "evaluation_summary_path": str(
                    (evaluation_root / str(trial["name"]) / "summary.json").resolve()
                ),
            }
        )
    selected = max(rows, key=lambda row: tuple(row["rank_key"]))
    result = {
        "schema_version": "studyhub.agent.router_rl.grpo_sweep_results.v2",
        "trials": rows,
        "selected_trial": selected["name"],
        "selected_config": selected["config"],
        "selection_rule": [
            "raw hard-gate floor",
            "fewest family regressions",
            "family choice floor",
            "overall raw choice success",
            "raw episode success",
            "raw reward",
            "lowest constraint severity",
        ],
        "required_lora_ranks_compared": sorted(
            {int(row["config"]["lora_rank"]) for row in rows}
        )
        == [8, 16, 32],
        "required_hyperparameter_axes_compared": all(
            len({row["config"][name] for row in rows}) >= 2
            for name in (
                "learning_rate",
                "reference_kl_beta",
                "group_size",
                "trajectory_discount",
            )
        ),
        "test_read": False,
        "sealed_read": False,
        "production_access": False,
    }
    output_path = evaluation_root / "sweep_results.json"
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    evaluate_parser = subparsers.add_parser("evaluate-shard")
    evaluate_parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    evaluate_parser.add_argument("--evaluation-root", type=Path, default=DEFAULT_EVALUATION_ROOT)
    evaluate_parser.add_argument("--shard", type=int, choices=(0, 1), required=True)
    evaluate_parser.add_argument("--device", default="cuda:0")
    summarize_parser = subparsers.add_parser("summarize")
    summarize_parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    summarize_parser.add_argument("--evaluation-root", type=Path, default=DEFAULT_EVALUATION_ROOT)
    args = parser.parse_args()
    if args.command == "evaluate-shard":
        result: Any = evaluate_shard(
            manifest_path=args.manifest.resolve(),
            evaluation_root=args.evaluation_root.resolve(),
            shard=args.shard,
            device=args.device,
        )
    else:
        result = summarize_sweep(
            manifest_path=args.manifest.resolve(),
            evaluation_root=args.evaluation_root.resolve(),
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
