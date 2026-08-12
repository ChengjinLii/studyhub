"""Prepare and run the preregistered GRPO LoRA/hyperparameter screen."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..spec import sha256_file
from .train_grpo import ALGORITHM, SCHEMA_VERSION, train_grpo

ROOT = Path(__file__).resolve().parents[4]
ARTIFACT_ROOT = ROOT / "training_artifacts/studyhub_agent_rl/router_rl_maturity_v2"
SWEEP_ROOT = ARTIFACT_ROOT / "experiments/grpo_sweep"
SEED = 26_081_211
TRIALS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("rank16_base", {}),
    ("rank8", {"lora_rank": 8, "lora_alpha": 16}),
    ("rank32", {"lora_rank": 32, "lora_alpha": 64}),
    ("lr_5e-6", {"learning_rate": 5e-6}),
    ("lr_2e-5", {"learning_rate": 2e-5}),
    ("kl_0.01", {"reference_kl_beta": 0.01}),
    ("kl_0.05", {"reference_kl_beta": 0.05}),
    ("group_3", {"group_size": 3}),
    ("group_5", {"group_size": 5}),
    ("discount_0.90", {"trajectory_discount": 0.90}),
    ("discount_0.99", {"trajectory_discount": 0.99}),
)


def prepare_sweep(*, output_dir: Path = SWEEP_ROOT) -> dict[str, Any]:
    configs_dir = output_dir / "configs"
    if configs_dir.exists() and any(configs_dir.iterdir()):
        raise FileExistsError(f"refusing to overwrite sweep configs: {configs_dir}")
    configs_dir.mkdir(parents=True, exist_ok=True)
    base: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "algorithm": ALGORITHM,
        "model_path": str(
            (ROOT / "training_artifacts/studyhub_agent_sft/qwen35_2b_router_v1_7_merged").resolve()
        ),
        "train_path": str((ARTIFACT_ROOT / "train.jsonl").resolve()),
        "reference_cache_path": str((ARTIFACT_ROOT / "reference/train_reference.jsonl").resolve()),
        "lora_rank": 16,
        "lora_alpha": 32,
        "lora_dropout": 0.0,
        "rollout_updates": 20,
        "group_size": 4,
        "material_episodes_per_update": 1,
        "boundary_episodes_per_update": 2,
        "policy_epochs": 2,
        "action_temperature": 1.25,
        "learning_rate": 1e-5,
        "adam_beta1": 0.9,
        "adam_beta2": 0.95,
        "weight_decay": 0.0,
        "reference_kl_beta": 0.02,
        "clip_epsilon": 0.2,
        "entropy_beta": 0.0,
        "trajectory_discount": 0.95,
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
        config_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
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
        "schema_version": "studyhub.agent.router_rl.grpo_sweep.v2",
        "status": "prepared",
        "trials": rows,
        "required_lora_ranks": [8, 16, 32],
        "required_hyperparameter_axes": [
            "learning_rate",
            "reference_kl_beta",
            "group_size",
            "trajectory_discount",
        ],
        "selection_split": "validation",
        "test_read": False,
        "sealed_read": False,
        "production_access": False,
    }
    manifest_path = output_dir / "sweep_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def run_shard(*, manifest_path: Path, shard: int) -> list[dict[str, Any]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    results: list[dict[str, Any]] = []
    for trial in manifest["trials"]:
        if int(trial["shard"]) != shard:
            continue
        config_path = Path(trial["config_path"])
        config = json.loads(config_path.read_text(encoding="utf-8"))
        run_dir = Path(config["output_root"]) / f"seed_{int(trial['seed'])}"
        summary_path = run_dir / "run_summary.json"
        if summary_path.is_file():
            results.append(json.loads(summary_path.read_text(encoding="utf-8")))
            continue
        if run_dir.exists() and any(run_dir.iterdir()):
            raise RuntimeError(f"partial sweep trial requires manual audit: {run_dir}")
        results.append(
            train_grpo(
                config_path=config_path,
                seed=int(trial["seed"]),
            )
        )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--output-dir", type=Path, default=SWEEP_ROOT)
    run = subparsers.add_parser("run-shard")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--shard", type=int, choices=(0, 1), required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        result: Any = prepare_sweep(output_dir=args.output_dir.resolve())
    else:
        result = run_shard(manifest_path=args.manifest.resolve(), shard=args.shard)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
