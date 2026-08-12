"""Freeze the formal GRPO configuration from Validation-only sweep evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..spec import sha256_file
from .train_grpo import ALGORITHM, SCHEMA_VERSION, GRPOConfig

ROOT = Path(__file__).resolve().parents[4]
ARTIFACT_ROOT = ROOT / "training_artifacts/studyhub_agent_rl/router_rl_maturity_v2"
DEFAULT_PRIMARY_RESULTS = (
    ROOT
    / "evaluation_artifacts/studyhub_agent/router_rl_maturity_v2/validation/grpo_sweep/sweep_results.json"
)
DEFAULT_FAILED_SCALE_RESULTS = (
    ROOT
    / "evaluation_artifacts/studyhub_agent/router_rl_maturity_v2/validation/grpo_scale_sweep/scale_sweep_results.json"
)
DEFAULT_STABILITY_RESULTS = (
    ROOT
    / "evaluation_artifacts/studyhub_agent/router_rl_maturity_v2/validation/grpo_stability_sweep/stability_sweep_results.json"
)
DEFAULT_OUTPUT = (
    ROOT / "ml/agentic_platform/rl/configs/router_grpo_maturity_v2_formal.json"
)


def build_formal_config(
    *,
    primary_results_path: Path,
    failed_scale_results_path: Path,
    stability_results_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Create one immutable 500-update config without reading Test or Sealed."""

    if output_path.exists():
        raise FileExistsError(f"formal config is already frozen: {output_path}")
    primary = _read_json(primary_results_path)
    failed_scale = _read_json(failed_scale_results_path)
    stability = _read_json(stability_results_path)
    _validate_selection_evidence(primary, failed_scale, stability)
    selected = stability["selected_config"]
    selected_trial = next(
        trial
        for trial in stability["trials"]
        if trial.get("name") == stability["selected_trial"]
    )
    policy_epochs = 2
    rollout_updates = 500
    screen_optimizer_updates = int(selected_trial["training"]["optimizer_updates"])
    decay_fraction = min(
        float(selected["learning_rate_decay_optimizer_updates"])
        / screen_optimizer_updates,
        1.0,
    )
    formal_decay_optimizer_updates = max(
        1,
        round(rollout_updates * policy_epochs * decay_fraction),
    )
    config: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "algorithm": ALGORITHM,
        "model_path": str(
            (ROOT / "training_artifacts/studyhub_agent_sft/qwen35_2b_router_v1_7_merged").resolve()
        ),
        "train_path": str((ARTIFACT_ROOT / "train.jsonl").resolve()),
        "reference_cache_path": str(
            (ARTIFACT_ROOT / "reference/train_reference.jsonl").resolve()
        ),
        "output_root": str((ARTIFACT_ROOT / "experiments/grpo_formal").resolve()),
        "lora_rank": int(selected["lora_rank"]),
        "lora_alpha": int(selected["lora_rank"]) * 2,
        "lora_dropout": 0.0,
        "rollout_updates": rollout_updates,
        "group_size": int(selected["group_size"]),
        "material_episodes_per_update": int(
            selected["material_episodes_per_update"]
        ),
        "boundary_episodes_per_update": int(
            selected["boundary_episodes_per_update"]
        ),
        "policy_epochs": policy_epochs,
        "action_temperature": float(selected["action_temperature"]),
        "learning_rate": float(selected["learning_rate"]),
        "learning_rate_schedule": str(selected["learning_rate_schedule"]),
        "learning_rate_decay_optimizer_updates": formal_decay_optimizer_updates,
        "learning_rate_min_ratio": float(selected["learning_rate_min_ratio"]),
        "adam_beta1": 0.9,
        "adam_beta2": 0.95,
        "weight_decay": 0.0,
        "reference_kl_beta": float(selected["reference_kl_beta"]),
        "clip_epsilon": 0.2,
        "entropy_beta": float(selected["entropy_beta"]),
        "trajectory_discount": float(selected["trajectory_discount"]),
        "terminal_bonus": 0.4,
        "failure_penalty": 0.4,
        "max_grad_norm": 1.0,
        "max_prompt_tokens": 4096,
        "checkpoint_every": 100,
        "gradient_checkpointing": True,
        "device": "cuda:0",
        "formal_run": True,
        "selection_evidence": {
            "split": "validation",
            "primary_trial": primary["selected_trial"],
            "failed_scale_best_screen_trial": failed_scale["best_screen_trial"],
            "failed_scale_gate_passed": False,
            "stability_trial": stability["selected_trial"],
            "screen_optimizer_updates": screen_optimizer_updates,
            "screen_decay_optimizer_updates": int(
                selected["learning_rate_decay_optimizer_updates"]
            ),
            "decay_fraction_of_screen_optimizer_updates": decay_fraction,
            "formal_decay_optimizer_updates": formal_decay_optimizer_updates,
            "primary_results_path": str(primary_results_path.resolve()),
            "primary_results_sha256": sha256_file(primary_results_path),
            "failed_scale_results_path": str(failed_scale_results_path.resolve()),
            "failed_scale_results_sha256": sha256_file(
                failed_scale_results_path
            ),
            "stability_results_path": str(stability_results_path.resolve()),
            "stability_results_sha256": sha256_file(stability_results_path),
            "test_read": False,
            "sealed_read": False,
        },
        "formal_protocol": {
            "seeds": [3407, 7703, 9109, 6209, 11213],
            "pause_after_update": 100,
            "resume_from_update": 100,
            "minimum_trajectory_rollouts_per_seed": 10_000,
            "minimum_optimizer_updates_per_seed": 500,
        },
        "isolation": {
            "production_access_allowed": False,
            "paid_material_allowed": False,
            "test_read_allowed": False,
            "sealed_read_allowed": False,
            "production_final_holdout_allowed": False,
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(f".{output_path.name}.tmp")
    if temporary_path.exists():
        raise FileExistsError(f"formal config staging file already exists: {temporary_path}")
    temporary_path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    try:
        # Re-load through the trainer's authoritative validation before freezing it.
        loaded = GRPOConfig.load(temporary_path)
        if loaded.planned_trajectory_rollouts < 10_000:
            raise AssertionError("formal config does not meet the rollout floor")
    except Exception:
        temporary_path.unlink()
        raise
    temporary_path.replace(output_path)
    return config


def _validate_selection_evidence(
    primary: dict[str, Any],
    failed_scale: dict[str, Any],
    stability: dict[str, Any],
) -> None:
    for name, value in (
        ("primary", primary),
        ("failed scale", failed_scale),
        ("stability", stability),
    ):
        if value.get("test_read") is not False or value.get("sealed_read") is not False:
            raise ValueError(f"{name} sweep accessed a locked split")
        if value.get("production_access") is not False:
            raise ValueError(f"{name} sweep accessed production")
    if not primary.get("selected_trial") or not isinstance(
        primary.get("selected_config"), dict
    ):
        raise ValueError("primary sweep has no selected Validation configuration")
    if (
        failed_scale.get("gate_passed") is not False
        or failed_scale.get("selected_trial") is not None
        or failed_scale.get("selected_config") is not None
    ):
        raise ValueError("failed scale sweep must remain rejected by its Gate")
    if (
        stability.get("gate_passed") is not True
        or not stability.get("selected_trial")
        or not isinstance(stability.get("selected_config"), dict)
    ):
        raise ValueError("stability sweep has no Gate-passing Validation configuration")
    if primary.get("required_lora_ranks_compared") is not True:
        raise ValueError("formal config requires the r8/r16/r32 comparison")
    if primary.get("required_hyperparameter_axes_compared") is not True:
        raise ValueError("formal config requires all primary hyperparameter axes")
    if failed_scale.get("required_group_scale_compared") is not True:
        raise ValueError("formal config requires group-size scale comparison")
    if failed_scale.get("required_entropy_scale_compared") is not True:
        raise ValueError("formal config requires entropy scale comparison")
    if stability.get("required_mixture_control_compared") is not True:
        raise ValueError("formal config requires an episode-mixture control")
    if stability.get("required_decay_horizons_compared") is not True:
        raise ValueError("formal config requires learning-rate decay comparison")
    if stability.get("required_schedule_shapes_compared") is not True:
        raise ValueError("formal config requires schedule-shape comparison")
    matching_trials = [
        trial
        for trial in stability.get("trials") or []
        if trial.get("name") == stability["selected_trial"]
    ]
    if (
        len(matching_trials) != 1
        or matching_trials[0].get("config") != stability.get("selected_config")
        or matching_trials[0].get("formal_eligible") is not True
        or matching_trials[0].get("validation_gate", {}).get("passed") is not True
        or int(
            matching_trials[0].get("training", {}).get("optimizer_updates", 0)
        )
        < 1
    ):
        raise ValueError("selected stability trial is not eligible for formal training")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primary-results", type=Path, default=DEFAULT_PRIMARY_RESULTS)
    parser.add_argument(
        "--failed-scale-results", type=Path, default=DEFAULT_FAILED_SCALE_RESULTS
    )
    parser.add_argument(
        "--stability-results", type=Path, default=DEFAULT_STABILITY_RESULTS
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = build_formal_config(
        primary_results_path=args.primary_results.resolve(),
        failed_scale_results_path=args.failed_scale_results.resolve(),
        stability_results_path=args.stability_results.resolve(),
        output_path=args.output.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
