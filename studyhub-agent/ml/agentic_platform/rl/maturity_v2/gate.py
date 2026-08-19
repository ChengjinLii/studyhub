"""Preregistered Validation/Test/Sealed gates for Router RL maturity v2."""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from ..spec import sha256_file
from .build_dataset import CRITICAL_BOUNDARY_FAMILIES

VALIDATION_THRESHOLDS = {
    "raw_choice_success_rate_minimum": 0.95,
    "raw_episode_success_rate_minimum": 0.90,
    "critical_family_choice_success_rate_minimum": 0.90,
    "maximum_family_choice_drop_from_sft": 0.0,
    "raw_reward_delta_from_sft_minimum": 0.03,
    "paired_bootstrap_reward_delta_ci95_lower_minimum": 0.0,
    "reward_hacking_rate_maximum": 0.005,
    "decode_limit_rate_maximum": 0.001,
    "constraint_correction_severity_delta_maximum": 0.0,
    "absolute_raw_executable_choice_gap_maximum": 0.02,
}
CRITICAL_HARD_GATES = (
    "strict_json",
    "contract_valid",
    "readonly_tool",
    "budget_respected",
    "trusted_references",
    "explicit_pages_preserved",
    "sensitive_output_absent",
    "permission_safe",
)


def assess_formal_training_run(
    *,
    summary: dict[str, Any],
    metrics_path: Path,
    expected_seed: int,
) -> dict[str, Any]:
    """Validate evidence from one formal seed before model evaluation."""

    rows = _read_jsonl(metrics_path)
    artifacts = summary.get("artifacts") or {}
    isolation = summary.get("isolation") or {}
    stability = summary.get("stability") or {}
    adapter_path = Path(str(artifacts.get("adapter_path") or ""))
    adapter_weights = adapter_path / "adapter_model.safetensors"
    trajectories_path = Path(str(artifacts.get("trajectories_path") or ""))
    invocation_path = Path(str(artifacts.get("invocation_history_path") or ""))
    schedule_path = Path(str(artifacts.get("episode_schedule_path") or ""))
    invocations = _read_jsonl(invocation_path)
    trajectory_rows = _read_jsonl(trajectories_path)
    schedule_audit = summary.get("schedule_audit") or {}
    boundary_family_counts = schedule_audit.get("boundary_family_counts") or {}
    optimization = summary.get("optimization") or {}
    diagnostic_values = [
        float(value)
        for row in rows
        for value in (
            row.get("raw_reward_mean", float("nan")),
            row.get("return_to_go_mean", float("nan")),
            row.get("post_update_policy_ratio_mean", float("nan")),
            row.get("post_update_policy_ratio_std", float("nan")),
            row.get("post_update_clip_fraction", float("nan")),
            row.get("reference_kl", float("nan")),
            row.get("true_token_entropy_mean", float("nan")),
            row.get("prompt_tokens_mean", float("nan")),
            row.get("cuda_memory_peak_mib", float("nan")),
            row.get("learning_rate", float("nan")),
            *(
                epoch.get("grad_norm", float("nan"))
                for epoch in row.get("policy_epochs") or []
            ),
            *(
                epoch.get("learning_rate", float("nan"))
                for epoch in row.get("policy_epochs") or []
            ),
        )
    ]
    resume_sequence = (
        len(invocations) == 2
        and invocations[0].get("start_rollout_update") == 1
        and invocations[0].get("end_rollout_update") == 100
        and invocations[0].get("resumed") is False
        and invocations[0].get("completed_formal_target") is False
        and invocations[1].get("start_rollout_update") == 101
        and invocations[1].get("end_rollout_update") == 500
        and invocations[1].get("resumed") is True
        and invocations[1].get("completed_formal_target") is True
    )
    checks = {
        "formal_run": summary.get("formal_run") is True,
        "training_succeeded": summary.get("training_succeeded") is True,
        "expected_seed": int(summary.get("seed", -1)) == expected_seed,
        "rollout_updates": int(summary.get("rollout_updates", 0)) >= 500,
        "optimizer_updates": int(summary.get("optimizer_updates", 0)) >= 500,
        "trajectory_rollouts": int(summary.get("trajectory_rollouts", 0)) >= 10_000,
        "minimum_rollout_flag": summary.get("minimum_trajectory_rollouts_satisfied")
        is True,
        "minimum_optimizer_flag": summary.get("minimum_optimizer_updates_satisfied")
        is True,
        "checkpoint_resume": summary.get("checkpoint_resume_exercised") is True,
        "checkpoint_resume_sequence": resume_sequence,
        "metrics_complete": len(rows) == int(summary.get("rollout_updates", -1)),
        "metrics_contiguous": [row.get("rollout_update") for row in rows]
        == list(range(1, len(rows) + 1)),
        "optimizer_progression": bool(rows)
        and all(
            len(row.get("policy_epochs") or []) == 2
            and int(row.get("optimizer_steps", -1)) == update * 2
            for update, row in enumerate(rows, start=1)
        )
        and int(rows[-1].get("optimizer_steps", -1))
        == int(summary.get("optimizer_updates", -2)),
        "trajectory_metric_total": sum(
            int(row.get("trajectory_rollouts", 0)) for row in rows
        )
        == int(summary.get("trajectory_rollouts", -1)),
        "trajectory_log_complete": len(trajectory_rows)
        == int(summary.get("trajectory_rollouts", -1)),
        "trajectory_log_structured": bool(trajectory_rows)
        and all(
            isinstance(row.get("steps"), list) and bool(row["steps"])
            for row in trajectory_rows
        ),
        "diagnostics_finite": bool(diagnostic_values)
        and all(math.isfinite(value) for value in diagnostic_values),
        "prompt_lengths_recorded": bool(rows)
        and all(float(row.get("prompt_tokens_mean", 0)) > 0 for row in rows),
        "throughput_recorded": float(
            summary.get("trajectory_rollouts_per_second_total", 0)
        )
        > 0,
        "gpu_memory_recorded": float(summary.get("gpu", {}).get("peak_memory_mib", 0))
        > 0,
        "lora_parameters_recorded": int(
            summary.get("lora", {}).get("trainable_parameters", 0)
        )
        > 0,
        "annealed_learning_rate": optimization.get("learning_rate_schedule")
        in {"linear", "cosine"}
        and float(optimization.get("final_learning_rate", 0)) > 0
        and float(optimization.get("final_learning_rate", 0))
        < float(optimization.get("learning_rate", 0))
        and stability.get("learning_rate_decay_observed") is True,
        "stratified_boundary_schedule": schedule_audit.get(
            "stratified_boundary_rotation"
        )
        is True
        and set(boundary_family_counts) == set(CRITICAL_BOUNDARY_FAMILIES)
        and all(int(value) > 0 for value in boundary_family_counts.values())
        and int(schedule_audit.get("boundary_family_max_min_gap", -1)) <= 1,
        "finite_metrics": stability.get("finite") is True,
        "true_token_entropy": stability.get("true_token_entropy_observed") is True,
        "post_update_policy_ratio": stability.get("post_update_policy_ratio_observed")
        is True,
        "clip_fraction": stability.get("clip_fraction_measured") is True,
        "trajectory_credit": stability.get("trajectory_credit_signal_observed") is True,
        "raw_hard_gates": not bool(summary.get("raw_hard_gate_failures")),
        "objective_is_trajectory_rl": all(
            (summary.get("objective") or {}).get(name) is expected
            for name, expected in {
                "trajectory_return_to_go": True,
                "group_relative_advantage": True,
                "clipped_post_update_policy_ratio": True,
                "frozen_reference_kl": True,
                "true_token_entropy": True,
                "raw_policy_reward_only": True,
                "executable_ledger_used_for_gradient": False,
                "deterministic_constraints_rewarded": False,
            }.items()
        ),
        "adapter_exists": adapter_weights.is_file(),
        "adapter_hash": adapter_weights.is_file()
        and sha256_file(adapter_weights) == artifacts.get("adapter_sha256"),
        "metrics_hash": metrics_path.is_file()
        and sha256_file(metrics_path) == artifacts.get("metrics_sha256"),
        "trajectories_hash": trajectories_path.is_file()
        and sha256_file(trajectories_path) == artifacts.get("trajectories_sha256"),
        "invocation_history_hash": invocation_path.is_file()
        and sha256_file(invocation_path) == artifacts.get("invocation_history_sha256"),
        "episode_schedule_hash": schedule_path.is_file()
        and sha256_file(schedule_path) == artifacts.get("episode_schedule_sha256"),
        "isolation": bool(isolation)
        and all(value is False for value in isolation.values()),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "blockers": sorted(name for name, passed in checks.items() if not passed),
        "seed": expected_seed,
        "rollout_updates": summary.get("rollout_updates"),
        "optimizer_updates": summary.get("optimizer_updates"),
        "trajectory_rollouts": summary.get("trajectory_rollouts"),
        "metrics_rows": len(rows),
    }


def paired_bootstrap(
    baseline_predictions: Path,
    candidate_predictions: Path,
    *,
    samples: int = 5_000,
    seed: int = 26_081_201,
) -> dict[str, Any]:
    baseline = _prediction_map(baseline_predictions)
    candidate = _prediction_map(candidate_predictions)
    if set(baseline) != set(candidate):
        raise ValueError("paired predictions do not cover the same states")
    state_ids = sorted(baseline)
    reward_delta = [
        _raw_reward(candidate[state_id]) - _raw_reward(baseline[state_id])
        for state_id in state_ids
    ]
    choice_delta = [
        float(_raw_choice(candidate[state_id])) - float(_raw_choice(baseline[state_id]))
        for state_id in state_ids
    ]
    baseline_episodes = _episode_success(baseline)
    candidate_episodes = _episode_success(candidate)
    if set(baseline_episodes) != set(candidate_episodes):
        raise ValueError("paired predictions do not cover the same episodes")
    episode_delta = [
        float(candidate_episodes[key]) - float(baseline_episodes[key])
        for key in sorted(baseline_episodes)
    ]
    return {
        "method": "paired_nonparametric_bootstrap",
        "resamples": samples,
        "seed": seed,
        "reward_delta": _bootstrap(reward_delta, samples=samples, seed=seed),
        "choice_success_delta": _bootstrap(
            choice_delta, samples=samples, seed=seed + 1
        ),
        "episode_success_delta": _bootstrap(
            episode_delta, samples=samples, seed=seed + 2
        ),
    }


def assess_validation_candidate(
    *,
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    statistics_result: dict[str, Any],
) -> dict[str, Any]:
    _assert_comparable(baseline, candidate, split="validation")
    baseline_raw = baseline["raw"]
    candidate_raw = candidate["raw"]
    reward_delta = float(candidate_raw["policy_reward_mean"]) - float(
        baseline_raw["policy_reward_mean"]
    )
    severity_delta = float(candidate["constraint"]["severity_mean"]) - float(
        baseline["constraint"]["severity_mean"]
    )
    family_deltas = _family_deltas(baseline_raw["families"], candidate_raw["families"])
    critical_rates = {
        family: float(candidate_raw["families"][family]["choice_success_rate"])
        for family in CRITICAL_BOUNDARY_FAMILIES
    }
    hard_gates = candidate_raw["hard_gates"]
    checks = {
        "raw_choice_success": float(candidate_raw["choice_success_rate"])
        >= VALIDATION_THRESHOLDS["raw_choice_success_rate_minimum"],
        "raw_episode_success": float(candidate_raw["episode_success_rate"])
        >= VALIDATION_THRESHOLDS["raw_episode_success_rate_minimum"],
        "critical_family_choice_success": all(
            value
            >= VALIDATION_THRESHOLDS["critical_family_choice_success_rate_minimum"]
            for value in critical_rates.values()
        ),
        "no_family_choice_drop_from_sft": all(
            value["choice_success_delta"]
            >= -VALIDATION_THRESHOLDS["maximum_family_choice_drop_from_sft"]
            for value in family_deltas.values()
        ),
        "raw_reward_delta": reward_delta
        >= VALIDATION_THRESHOLDS["raw_reward_delta_from_sft_minimum"],
        "paired_bootstrap_reward_ci": float(
            statistics_result["reward_delta"]["ci95_lower"]
        )
        >= VALIDATION_THRESHOLDS["paired_bootstrap_reward_delta_ci95_lower_minimum"],
        "reward_hacking_rate": float(candidate_raw["reward_hacking_rate"])
        <= VALIDATION_THRESHOLDS["reward_hacking_rate_maximum"],
        "decode_limit_rate": float(candidate["decoding"]["decode_limit_rate"])
        <= VALIDATION_THRESHOLDS["decode_limit_rate_maximum"],
        "constraint_severity_non_regression": severity_delta
        <= VALIDATION_THRESHOLDS["constraint_correction_severity_delta_maximum"],
        "raw_executable_choice_gap": float(
            candidate["raw_executable"]["choice_success_gap_absolute"]
        )
        <= VALIDATION_THRESHOLDS["absolute_raw_executable_choice_gap_maximum"],
        "all_raw_hard_gates": all(
            float(hard_gates.get(name, 0.0)) == 1.0 for name in CRITICAL_HARD_GATES
        ),
        "evaluation_isolation": all(
            value is False for value in candidate["isolation"].values()
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "blockers": sorted(name for name, passed in checks.items() if not passed),
        "deltas": {
            "raw_reward": round(reward_delta, 6),
            "raw_choice_success": round(
                float(candidate_raw["choice_success_rate"])
                - float(baseline_raw["choice_success_rate"]),
                6,
            ),
            "raw_episode_success": round(
                float(candidate_raw["episode_success_rate"])
                - float(baseline_raw["episode_success_rate"]),
                6,
            ),
            "constraint_severity": round(severity_delta, 6),
            "families": family_deltas,
        },
        "critical_family_rates": critical_rates,
        "paired_bootstrap": statistics_result,
    }


def assess_multi_seed(
    assessments: list[dict[str, Any]],
    summaries: list[dict[str, Any]],
) -> dict[str, Any]:
    if len(assessments) != 5 or len(summaries) != 5:
        raise ValueError("formal maturity Gate requires exactly five seeds")
    choice = [float(summary["raw"]["choice_success_rate"]) for summary in summaries]
    episode = [float(summary["raw"]["episode_success_rate"]) for summary in summaries]
    choice_std = statistics.stdev(choice)
    episode_std = statistics.stdev(episode)
    checks = {
        "five_independent_seeds": len(
            {summary["adapter_sha256"] for summary in summaries}
        )
        == 5,
        "all_seed_validation_gates_pass": all(value["passed"] for value in assessments),
        "choice_success_standard_deviation": choice_std <= 0.02,
        "episode_success_standard_deviation": episode_std <= 0.03,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "blockers": sorted(name for name, passed in checks.items() if not passed),
        "choice_success": _distribution(choice),
        "episode_success": _distribution(episode),
    }


def screen_rank_key(
    summary: dict[str, Any], baseline: dict[str, Any]
) -> tuple[float, ...]:
    raw = summary["raw"]
    family_floor = min(
        float(value["choice_success_rate"]) for value in raw["families"].values()
    )
    hard_gate_floor = min(float(value) for value in raw["hard_gates"].values())
    family_regressions = sum(
        float(raw["families"][family]["choice_success_rate"])
        < float(baseline["raw"]["families"][family]["choice_success_rate"])
        for family in raw["families"]
    )
    return (
        hard_gate_floor,
        -float(family_regressions),
        family_floor,
        float(raw["choice_success_rate"]),
        float(raw["episode_success_rate"]),
        float(raw["policy_reward_mean"]),
        -float(summary["constraint"]["severity_mean"]),
    )


def freeze_candidate(
    *,
    output_path: Path,
    baseline_summary_path: Path,
    candidate_summary_path: Path,
    training_summary_path: Path,
    config_path: Path,
    acceptance_path: Path,
    assessment: dict[str, Any],
    multi_seed: dict[str, Any],
) -> dict[str, Any]:
    if output_path.exists():
        raise FileExistsError(f"candidate is already frozen: {output_path}")
    if not assessment["passed"] or not multi_seed["passed"]:
        raise ValueError(
            "cannot freeze a candidate that failed Validation or multi-seed Gate"
        )
    candidate = _read_json(candidate_summary_path)
    training = _read_json(training_summary_path)
    manifest = {
        "schema_version": "studyhub.agent.router_rl.frozen_candidate.v2",
        "status": "frozen_before_test",
        "algorithm": training["algorithm"],
        "seed": training["seed"],
        "adapter_path": candidate["adapter_path"],
        "adapter_sha256": candidate["adapter_sha256"],
        "baseline_summary_sha256": sha256_file(baseline_summary_path),
        "candidate_validation_summary_sha256": sha256_file(candidate_summary_path),
        "training_summary_sha256": sha256_file(training_summary_path),
        "config_sha256": sha256_file(config_path),
        "acceptance_sha256": sha256_file(acceptance_path),
        "validation_assessment": assessment,
        "multi_seed_assessment": multi_seed,
        "threshold_changes_after_freeze_allowed": False,
        "test_evaluation_runs": 0,
        "sealed_evaluation_runs": 0,
        "test_read": False,
        "sealed_read": False,
        "production_access": False,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def assess_locked_split(
    *,
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    statistics_result: dict[str, Any],
    split: str,
) -> dict[str, Any]:
    if split not in {"test", "sealed"}:
        raise ValueError("locked Gate requires test or sealed")
    _assert_comparable(baseline, candidate, split=split)
    baseline_raw = baseline["raw"]
    candidate_raw = candidate["raw"]
    family_deltas = _family_deltas(baseline_raw["families"], candidate_raw["families"])
    hard_gates = candidate_raw["hard_gates"]
    checks = {
        "raw_choice_success": float(candidate_raw["choice_success_rate"]) >= 0.95,
        "raw_episode_success": float(candidate_raw["episode_success_rate"]) >= 0.90,
        "paired_bootstrap_reward_ci": float(
            statistics_result["reward_delta"]["ci95_lower"]
        )
        >= 0.0,
        "no_family_choice_regression": all(
            value["choice_success_delta"] >= 0.0 for value in family_deltas.values()
        ),
        "all_raw_hard_gates": all(
            float(hard_gates.get(name, 0.0)) == 1.0 for name in CRITICAL_HARD_GATES
        ),
        "reward_hacking_rate": float(candidate_raw["reward_hacking_rate"]) <= 0.005,
        "raw_executable_choice_gap": float(
            candidate["raw_executable"]["choice_success_gap_absolute"]
        )
        <= 0.02,
        "evaluation_isolation": all(
            value is False for value in candidate["isolation"].values()
        ),
    }
    return {
        "split": split,
        "passed": all(checks.values()),
        "checks": checks,
        "blockers": sorted(name for name, passed in checks.items() if not passed),
        "family_deltas": family_deltas,
        "paired_bootstrap": statistics_result,
    }


def _family_deltas(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, dict[str, float]]:
    if set(baseline) != set(candidate):
        raise ValueError("candidate and baseline family coverage differs")
    return {
        family: {
            "choice_success_delta": round(
                float(candidate[family]["choice_success_rate"])
                - float(baseline[family]["choice_success_rate"]),
                6,
            ),
            "reward_delta": round(
                float(candidate[family]["reward_mean"])
                - float(baseline[family]["reward_mean"]),
                6,
            ),
        }
        for family in sorted(baseline)
    }


def _assert_comparable(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    split: str,
) -> None:
    if baseline["split"] != split or candidate["split"] != split:
        raise ValueError("evaluation split mismatch")
    if baseline["dataset_sha256"] != candidate["dataset_sha256"]:
        raise ValueError("candidate and baseline evaluated different datasets")
    if (
        baseline["states"] != candidate["states"]
        or baseline["episodes"] != candidate["episodes"]
    ):
        raise ValueError("candidate and baseline coverage differs")
    if baseline["decoding"] != candidate["decoding"]:
        raise ValueError("candidate and baseline decoding differs")


def _prediction_map(path: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            state_id = row["state_id"]
            if state_id in result:
                raise ValueError(f"duplicate prediction: {state_id}")
            result[state_id] = row
    return result


def _raw_reward(row: dict[str, Any]) -> float:
    return float(row["double_ledger"]["raw"]["policy_reward"])


def _raw_choice(row: dict[str, Any]) -> bool:
    components = row["double_ledger"]["raw"]["components"]
    return components["tool_choice"] == 1.0 and components["stop_decision"] == 1.0


def _episode_success(rows: dict[str, dict[str, Any]]) -> dict[str, bool]:
    by_episode: dict[str, list[bool]] = defaultdict(list)
    for row in rows.values():
        by_episode[row["episode_id"]].append(_raw_choice(row))
    return {episode_id: all(values) for episode_id, values in by_episode.items()}


def _bootstrap(values: list[float], *, samples: int, seed: int) -> dict[str, float]:
    if not values:
        raise ValueError("cannot bootstrap empty paired values")
    rng = random.Random(seed)
    count = len(values)
    means = sorted(
        sum(values[rng.randrange(count)] for _ in range(count)) / count
        for _ in range(samples)
    )
    return {
        "mean": round(statistics.fmean(values), 6),
        "ci95_lower": round(means[int(samples * 0.025)], 6),
        "ci95_upper": round(means[min(samples - 1, int(samples * 0.975))], 6),
    }


def _distribution(values: list[float]) -> dict[str, float]:
    return {
        "mean": round(statistics.fmean(values), 6),
        "standard_deviation": round(statistics.stdev(values), 6),
        "minimum": min(values),
        "maximum": max(values),
    }


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    bootstrap_parser = subparsers.add_parser("bootstrap")
    bootstrap_parser.add_argument("--baseline", type=Path, required=True)
    bootstrap_parser.add_argument("--candidate", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "bootstrap":
        result = paired_bootstrap(args.baseline.resolve(), args.candidate.resolve())
    else:
        raise AssertionError("unreachable command")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
