"""Gate the isolated Router RL pilot with independent evaluation evidence."""

from __future__ import annotations

import argparse
import ast
import json
import math
import random
import statistics
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from ..paths import BACKEND_ROOT, WORKSPACE_ROOT
from .spec import sha256_file

SCHEMA_VERSION = "studyhub.agent.router_rl.pilot_gate.v1"
BOUNDARY_FAMILIES = {
    "direct_general_answer",
    "empty_search_rewrite",
    "force_final_budget",
    "memory_read",
    "permission_boundary",
    "synthesize_context",
    "untrusted_observation",
}
THRESHOLDS: dict[str, float] = {
    "minimum_reward_delta": 0.0,
    "minimum_choice_success_delta": 0.0,
    "minimum_episode_success_delta": 0.0,
    "minimum_hard_gate_delta": 0.0,
    "maximum_family_choice_drop": 0.10,
    "maximum_constraint_dependency_abs_increase": 0.02,
    "maximum_decode_limit_increase": 0.0,
    "maximum_reward_hacking_increase": 0.0,
    "maximum_training_kl": 0.02,
    "maximum_training_peak_memory_mib": 75_000.0,
}
EXPECTED_PRODUCTION_DEFAULTS: dict[str, Any] = {
    "ai_agent_dynamic_tools_enabled": False,
    "ai_agent_runtime_constraints_enabled": False,
    "agentic_model_provider": "disabled",
}


def assess_candidate(
    *,
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    paired_statistics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare one policy against the frozen SFT baseline without runtime masking."""
    integrity = _evaluation_integrity(baseline=baseline, candidate=candidate)
    baseline_raw = _mapping(baseline["raw"])
    candidate_raw = _mapping(candidate["raw"])
    baseline_executable = _mapping(baseline["executable"])
    candidate_executable = _mapping(candidate["executable"])
    reward_delta = _metric(candidate_raw, "policy_reward_mean") - _metric(baseline_raw, "policy_reward_mean")
    choice_delta = _metric(candidate_raw, "choice_success_rate") - _metric(baseline_raw, "choice_success_rate")
    episode_delta = _metric(candidate_raw, "episode_success_rate") - _metric(baseline_raw, "episode_success_rate")
    baseline_gates = _mapping(baseline_raw["hard_gates"])
    candidate_gates = _mapping(candidate_raw["hard_gates"])
    hard_gate_deltas = {
        name: round(float(candidate_gates.get(name, 0.0)) - float(value), 6)
        for name, value in sorted(baseline_gates.items())
    }
    baseline_families = _mapping(baseline_raw["families"])
    candidate_families = _mapping(candidate_raw["families"])
    family_deltas = {
        name: {
            "choice_success_delta": round(
                _metric(_mapping(candidate_families.get(name, {})), "choice_success_rate")
                - _metric(_mapping(value), "choice_success_rate"),
                6,
            ),
            "reward_delta": round(
                _metric(_mapping(candidate_families.get(name, {})), "reward_mean")
                - _metric(_mapping(value), "reward_mean"),
                6,
            ),
            "samples": int(_mapping(value).get("samples", 0)),
            "boundary_family": name in BOUNDARY_FAMILIES,
        }
        for name, value in sorted(baseline_families.items())
    }
    hacking_delta = _hacking_total(candidate_raw) - _hacking_total(baseline_raw)
    constraint_abs_increase = abs(float(candidate["constraint_dependency_delta_mean"])) - abs(
        float(baseline["constraint_dependency_delta_mean"])
    )
    decode_limit_delta = int(candidate["decode_limit_hits"]) - int(baseline["decode_limit_hits"])
    executable_reward_delta = _metric(candidate_executable, "policy_reward_mean") - _metric(
        baseline_executable, "policy_reward_mean"
    )
    executable_choice_delta = _metric(candidate_executable, "choice_success_rate") - _metric(
        baseline_executable, "choice_success_rate"
    )
    correction_count_delta = _correction_total(candidate) - _correction_total(baseline)
    checks = {
        "evaluation_integrity": all(integrity.values()),
        "raw_reward_non_regression": reward_delta >= THRESHOLDS["minimum_reward_delta"],
        "raw_choice_success_non_regression": choice_delta >= THRESHOLDS["minimum_choice_success_delta"],
        "raw_episode_success_non_regression": episode_delta >= THRESHOLDS["minimum_episode_success_delta"],
        "raw_hard_gates_non_regression": all(
            delta >= THRESHOLDS["minimum_hard_gate_delta"] for delta in hard_gate_deltas.values()
        ),
        "family_choice_drop_bounded": all(
            values["choice_success_delta"] >= -THRESHOLDS["maximum_family_choice_drop"]
            for values in family_deltas.values()
        ),
        "reward_hacking_non_regression": hacking_delta <= THRESHOLDS["maximum_reward_hacking_increase"],
        "decode_limit_non_regression": decode_limit_delta <= THRESHOLDS["maximum_decode_limit_increase"],
        "constraint_dependency_bounded": constraint_abs_increase
        <= THRESHOLDS["maximum_constraint_dependency_abs_increase"],
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "integrity": integrity,
        "deltas": {
            "raw_policy_reward": round(reward_delta, 6),
            "raw_choice_success_rate": round(choice_delta, 6),
            "raw_episode_success_rate": round(episode_delta, 6),
            "hard_gates": hard_gate_deltas,
            "families": family_deltas,
            "reward_hacking_count": hacking_delta,
            "decode_limit_hits": decode_limit_delta,
            "constraint_dependency_absolute": round(constraint_abs_increase, 6),
            "executable_policy_reward": round(executable_reward_delta, 6),
            "executable_choice_success_rate": round(executable_choice_delta, 6),
            "constraint_correction_count": correction_count_delta,
        },
        "constraint_projection_diagnostic": {
            "baseline_raw_to_executable_delta": float(baseline["constraint_dependency_delta_mean"]),
            "candidate_raw_to_executable_delta": float(candidate["constraint_dependency_delta_mean"]),
            "executable_policy_improved": executable_reward_delta >= 0.0,
            "executable_choice_improved": executable_choice_delta >= 0.0,
            "correction_count_increased": correction_count_delta > 0,
            "note": (
                "Diagnostic only: executable metrics cannot replace the raw-policy Gate because runtime constraints "
                "may mask model errors."
            ),
        },
        "paired_statistics": dict(paired_statistics or {}),
        "blockers": sorted(name for name, passed in checks.items() if not passed),
    }


def assess_training_run(summary: Mapping[str, Any], *, expected_rollouts: int) -> dict[str, Any]:
    stability = _mapping(summary.get("stability", {}))
    objective = _mapping(summary.get("objective", {}))
    isolation = _mapping(summary.get("isolation", {}))
    finite_metrics = [
        stability.get("mean_kl"),
        stability.get("max_kl"),
        stability.get("mean_clip_fraction"),
        stability.get("mean_entropy_proxy"),
        stability.get("mean_completion_tokens"),
        _mapping(summary.get("reward", {})).get("mean"),
    ]
    checks = {
        "training_succeeded": summary.get("training_succeeded") is True,
        "rollout_count_complete": int(summary.get("rollouts", -1)) == expected_rollouts,
        "finite_metrics": all(_finite(value) for value in finite_metrics),
        "kl_bounded": _finite(stability.get("max_kl"))
        and float(stability["max_kl"]) <= THRESHOLDS["maximum_training_kl"],
        "entropy_observed": _finite(stability.get("mean_entropy_proxy"))
        and float(stability["mean_entropy_proxy"]) > 0.0,
        "clip_fraction_valid": _finite(stability.get("mean_clip_fraction"))
        and 0.0 <= float(stability["mean_clip_fraction"]) <= 1.0,
        "gpu_memory_bounded": float(_mapping(summary.get("gpu", {})).get("peak_memory_mib", math.inf))
        <= THRESHOLDS["maximum_training_peak_memory_mib"],
        "raw_policy_ledger_used_for_gradient": objective.get("reward_ledger_used_for_gradient")
        == "raw_policy_proposal",
        "executable_ledger_not_used_for_gradient": objective.get("executable_ledger_used_for_gradient") is False,
        "deterministic_constraints_not_rewarded": objective.get("deterministic_constraints_rewarded") is False,
        "group_relative_advantage_enabled": objective.get("group_relative_advantage") is True,
        "reference_kl_enabled": float(objective.get("reference_kl_beta", 0.0)) > 0.0,
        "isolated_from_production": all(value is False for value in isolation.values()),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "blockers": sorted(name for name, passed in checks.items() if not passed),
    }


def paired_bootstrap_from_predictions(
    baseline_path: Path,
    candidate_path: Path,
    *,
    samples: int = 5_000,
    seed: int = 20260812,
) -> dict[str, Any]:
    baseline = _load_prediction_rows(baseline_path)
    candidate = _load_prediction_rows(candidate_path)
    if set(baseline) != set(candidate):
        raise ValueError("paired evaluation predictions do not cover the same states")
    state_ids = sorted(baseline)
    reward_deltas = [
        _prediction_reward(candidate[state_id]) - _prediction_reward(baseline[state_id]) for state_id in state_ids
    ]
    choice_deltas = [
        float(_prediction_choice(candidate[state_id])) - float(_prediction_choice(baseline[state_id]))
        for state_id in state_ids
    ]
    baseline_episodes = _episode_success_by_id(baseline)
    candidate_episodes = _episode_success_by_id(candidate)
    if set(baseline_episodes) != set(candidate_episodes):
        raise ValueError("paired evaluation predictions do not cover the same episodes")
    episode_deltas = [
        float(candidate_episodes[episode_id]) - float(baseline_episodes[episode_id])
        for episode_id in sorted(baseline_episodes)
    ]
    return {
        "method": "paired_nonparametric_bootstrap",
        "resamples": samples,
        "seed": seed,
        "reward_delta": _bootstrap_delta(reward_deltas, samples=samples, seed=seed),
        "choice_success_delta": _bootstrap_delta(choice_deltas, samples=samples, seed=seed + 1),
        "episode_success_delta": _bootstrap_delta(episode_deltas, samples=samples, seed=seed + 2),
    }


def gate_pilot(
    *,
    repo_root: Path,
    artifact_root: Path,
    evaluation_root: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    config = _read_json(repo_root / "ml/agentic_platform/rl/configs/router_grpo_pilot_v1.json")
    audit = _read_json(artifact_root / "audit.json")
    manifest = _read_json(artifact_root / "manifest.json")
    calibration = _read_json(artifact_root / "judge_calibration.json")
    input_lock = _read_json(artifact_root / "input_lock.json")
    seeds = [int(seed) for seed in config["seeds"]]
    expected_rollouts = int(config["train_states"]) * int(config["group_size"])
    training_summaries = {
        f"seed_{seed}": _read_json(artifact_root / "runs" / f"seed_{seed}" / "run_summary.json") for seed in seeds
    }
    training_assessments = {
        label: assess_training_run(summary, expected_rollouts=expected_rollouts)
        for label, summary in training_summaries.items()
    }
    validation_root = evaluation_root / "validation"
    baseline_validation_path = validation_root / "baseline_sft" / "summary.json"
    baseline_validation = _read_json(baseline_validation_path)
    validation_candidates = {
        f"seed_{seed}": _read_json(validation_root / f"seed_{seed}" / "summary.json") for seed in seeds
    }
    candidate_assessments: dict[str, Any] = {}
    for label, summary in validation_candidates.items():
        paired = paired_bootstrap_from_predictions(
            Path(str(baseline_validation["predictions_path"])),
            Path(str(summary["predictions_path"])),
        )
        candidate_assessments[label] = assess_candidate(
            baseline=baseline_validation,
            candidate=summary,
            paired_statistics=paired,
        )
    eligible = [label for label, result in candidate_assessments.items() if result["passed"]]
    selected_label = max(
        eligible,
        key=lambda label: float(_mapping(validation_candidates[label]["raw"])["policy_reward_mean"]),
        default=None,
    )
    reproducibility = _verify_input_lock(repo_root=repo_root, lock=input_lock)
    production_defaults = _read_production_defaults(BACKEND_ROOT / "app/core/config.py")
    production_defaults_safe = production_defaults == EXPECTED_PRODUCTION_DEFAULTS
    global_checks = {
        "dataset_audit_passed": audit.get("passed") is True,
        "material_split_isolated": not audit.get("material_split_leaks"),
        "query_split_isolated": not audit.get("query_split_leaks"),
        "paid_material_excluded": audit.get("paid_material_used") is False,
        "development_diagnostic_unread": audit.get("development_diagnostic_read") is False,
        "final_holdout_unread": audit.get("final_holdout_read") is False,
        "judge_calibration_passed": calibration.get("passed") is True
        and float(calibration.get("pairwise_accuracy", 0.0)) >= 0.90
        and float(calibration.get("serialization_invariance", 0.0)) == 1.0,
        "all_training_runs_passed": all(result["passed"] for result in training_assessments.values()),
        "input_lock_verified": all(reproducibility.values()),
        "production_defaults_safe": production_defaults_safe,
        "validation_candidate_selected": selected_label is not None,
    }
    multi_seed_statistics = _multi_seed_statistics(
        training_summaries=training_summaries,
        validation_summaries=validation_candidates,
    )
    selection = _selection_manifest(
        config=config,
        input_lock=input_lock,
        baseline=baseline_validation,
        selected_label=selected_label,
        selected=validation_candidates.get(selected_label) if selected_label else None,
        candidate_assessments=candidate_assessments,
    )
    test_result: dict[str, Any] | None = None
    test_root = evaluation_root / "test"
    baseline_test_path = test_root / "baseline_sft" / "summary.json"
    candidate_test_path = test_root / str(selected_label) / "summary.json" if selected_label else None
    if baseline_test_path.exists() != bool(candidate_test_path and candidate_test_path.exists()):
        raise ValueError("test evaluation is partial; baseline and frozen candidate must both exist")
    if baseline_test_path.exists() and candidate_test_path is not None and candidate_test_path.exists():
        baseline_test = _read_json(baseline_test_path)
        candidate_test = _read_json(candidate_test_path)
        test_result = assess_candidate(
            baseline=baseline_test,
            candidate=candidate_test,
            paired_statistics=paired_bootstrap_from_predictions(
                Path(str(baseline_test["predictions_path"])),
                Path(str(candidate_test["predictions_path"])),
            ),
        )
        test_result.update(
            {
                "baseline_summary_sha256": sha256_file(baseline_test_path),
                "candidate_summary_sha256": sha256_file(candidate_test_path),
                "selected_label": selected_label,
            }
        )
    global_passed = all(global_checks.values())
    pilot_passed = global_passed and test_result is not None and test_result["passed"] is True
    if not global_passed:
        conclusion = "NO_GO_VALIDATION"
    elif test_result is None:
        conclusion = "CONDITIONAL_GO_INDEPENDENT_TEST"
    elif pilot_passed:
        conclusion = "GO_NEXT_OFFLINE_ITERATION"
    else:
        conclusion = "NO_GO_INDEPENDENT_TEST"
    gate = {
        "schema_version": SCHEMA_VERSION,
        "conclusion": conclusion,
        "pilot_gate_passed": pilot_passed,
        "ready_for_next_offline_iteration": pilot_passed,
        "ready_for_production_rollout": False,
        "production_rollout_blockers": [
            "RL policy has not passed the untouched final production holdout.",
            "Teacher-reviewed Silver reward calibration is not human gold.",
            "No shadow traffic, canary or online rollback exercise has been run.",
        ],
        "thresholds": THRESHOLDS,
        "global_checks": global_checks,
        "global_blockers": sorted(name for name, passed in global_checks.items() if not passed),
        "dataset": {
            "manifest_sha256": sha256_file(artifact_root / "manifest.json"),
            "states": audit.get("states"),
            "episodes": audit.get("episodes"),
            "split_counts": audit.get("split_counts"),
            "family_counts": audit.get("family_counts"),
            "source_scope": _mapping(manifest.get("source", {})).get("access_scope"),
        },
        "judge_calibration": {
            "type": calibration.get("judge_type"),
            "cases": calibration.get("cases"),
            "pairwise_accuracy": calibration.get("pairwise_accuracy"),
            "serialization_invariance": calibration.get("serialization_invariance"),
            "human_gold": calibration.get("human_gold"),
            "limitations": calibration.get("limitations"),
        },
        "training_assessments": training_assessments,
        "multi_seed_statistics": multi_seed_statistics,
        "validation": {
            "baseline_summary_sha256": sha256_file(baseline_validation_path),
            "candidate_assessments": candidate_assessments,
            "selected_label": selected_label,
        },
        "independent_test": test_result,
        "reproducibility_checks": reproducibility,
        "production_defaults": production_defaults,
        "isolation": {
            "production_api_called": False,
            "production_database_accessed": False,
            "production_oss_write_called": False,
            "paid_material_used": False,
            "development_diagnostic_read": False,
            "final_holdout_read": False,
        },
    }
    release = _release_manifest(
        input_lock=input_lock,
        selection=selection,
        production_defaults=production_defaults,
        pilot_passed=pilot_passed,
    )
    return gate, selection, release


def _evaluation_integrity(
    *, baseline: Mapping[str, Any], candidate: Mapping[str, Any]
) -> dict[str, bool]:
    baseline_isolation = _mapping(baseline.get("isolation", {}))
    candidate_isolation = _mapping(candidate.get("isolation", {}))
    return {
        "same_split": candidate.get("split") == baseline.get("split")
        and candidate.get("split") in {"validation", "test"},
        "same_dataset": candidate.get("dataset_sha256") == baseline.get("dataset_sha256"),
        "same_decoding": candidate.get("decoding") == baseline.get("decoding"),
        "same_state_count": candidate.get("states") == baseline.get("states"),
        "complete_predictions": candidate.get("predictions") == candidate.get("states")
        and baseline.get("predictions") == baseline.get("states"),
        "distinct_adapter": candidate.get("adapter_sha256") != baseline.get("adapter_sha256"),
        "baseline_isolated": all(value is False for value in baseline_isolation.values()),
        "candidate_isolated": all(value is False for value in candidate_isolation.values()),
    }


def _multi_seed_statistics(
    *,
    training_summaries: Mapping[str, Mapping[str, Any]],
    validation_summaries: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    training_extractors: dict[str, Callable[[Mapping[str, Any]], float]] = {
        "reward_mean": lambda row: _metric(_mapping(row["reward"]), "mean"),
        "mean_kl": lambda row: _metric(_mapping(row["stability"]), "mean_kl"),
        "max_kl": lambda row: _metric(_mapping(row["stability"]), "max_kl"),
        "entropy_proxy": lambda row: _metric(_mapping(row["stability"]), "mean_entropy_proxy"),
        "completion_tokens": lambda row: _metric(_mapping(row["stability"]), "mean_completion_tokens"),
        "peak_memory_mib": lambda row: _metric(_mapping(row["gpu"]), "peak_memory_mib"),
    }
    validation_extractors: dict[str, Callable[[Mapping[str, Any]], float]] = {
        "raw_reward_mean": lambda row: _metric(_mapping(row["raw"]), "policy_reward_mean"),
        "raw_choice_success_rate": lambda row: _metric(_mapping(row["raw"]), "choice_success_rate"),
        "raw_episode_success_rate": lambda row: _metric(_mapping(row["raw"]), "episode_success_rate"),
        "constraint_dependency_delta": lambda row: float(row["constraint_dependency_delta_mean"]),
    }
    return {
        "method": "student_t_95ci_across_three_independent_seeds",
        "training": {
            name: _aggregate([extractor(row) for row in training_summaries.values()])
            for name, extractor in training_extractors.items()
        },
        "validation": {
            name: _aggregate([extractor(row) for row in validation_summaries.values()])
            for name, extractor in validation_extractors.items()
        },
    }


def _verify_input_lock(*, repo_root: Path, lock: Mapping[str, Any]) -> dict[str, bool]:
    config = _mapping(lock["config"])
    dataset = _mapping(lock["dataset"])
    policy = _mapping(lock["policy"])
    implementation = _mapping(lock["implementation_sha256"])
    checks = {
        "config_hash": sha256_file(Path(str(config["path"]))) == config["sha256"],
        "dataset_hash": sha256_file(Path(str(dataset["path"]))) == dataset["sha256"],
        "sft_adapter_hash": sha256_file(Path(str(policy["sft_adapter_path"])) / "adapter_model.safetensors")
        == policy["sft_adapter_sha256"],
        "base_config_hash": sha256_file(Path(str(policy["base_model_path"])) / "config.json")
        == policy["base_config_sha256"],
        "base_weight_index_hash": sha256_file(
            Path(str(policy["base_model_path"])) / "model.safetensors.index.json"
        )
        == policy["base_weight_index_sha256"],
        "tokenizer_config_hash": sha256_file(Path(str(policy["base_model_path"])) / "tokenizer_config.json")
        == policy["tokenizer_config_sha256"],
    }
    for relative_path, expected_hash in implementation.items():
        path = Path(relative_path)
        base = WORKSPACE_ROOT if path.parts and path.parts[0] == "backend" else repo_root
        checks[f"implementation:{relative_path}"] = sha256_file(base / path) == expected_hash
    return checks


def _read_production_defaults(path: Path) -> dict[str, Any]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    defaults: dict[str, Any] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name) or node.value is None:
            continue
        name = node.target.id
        if name in EXPECTED_PRODUCTION_DEFAULTS:
            defaults[name] = ast.literal_eval(node.value)
    return defaults


def _selection_manifest(
    *,
    config: Mapping[str, Any],
    input_lock: Mapping[str, Any],
    baseline: Mapping[str, Any],
    selected_label: str | None,
    selected: Mapping[str, Any] | None,
    candidate_assessments: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "studyhub.agent.router_rl.selection.v1",
        "selection_basis": "validation_only_raw_policy_double_ledger",
        "algorithm": config["algorithm"],
        "thresholds": THRESHOLDS,
        "baseline": {
            "adapter_path": baseline["adapter_path"],
            "adapter_sha256": baseline["adapter_sha256"],
        },
        "selected_label": selected_label,
        "selected_adapter_path": selected.get("adapter_path") if selected else None,
        "selected_adapter_sha256": selected.get("adapter_sha256") if selected else None,
        "eligible_labels": sorted(label for label, result in candidate_assessments.items() if result["passed"]),
        "candidate_blockers": {
            label: result["blockers"] for label, result in sorted(candidate_assessments.items())
        },
        "test_authorized": selected_label is not None,
        "test_metrics_used_for_selection": False,
        "final_holdout_read": False,
        "reference_adapter_sha256": _mapping(input_lock["reference_policy"])["adapter_sha256"],
    }


def _release_manifest(
    *,
    input_lock: Mapping[str, Any],
    selection: Mapping[str, Any],
    production_defaults: Mapping[str, Any],
    pilot_passed: bool,
) -> dict[str, Any]:
    policy = _mapping(input_lock["policy"])
    return {
        "schema_version": "studyhub.agent.router_rl.release_rollback.v1",
        "status": "research_only",
        "next_offline_iteration_allowed": pilot_passed,
        "production_deployment_allowed": False,
        "production_code_or_configuration_changed": False,
        "candidate": {
            "label": selection["selected_label"],
            "adapter_path": selection["selected_adapter_path"],
            "adapter_sha256": selection["selected_adapter_sha256"],
        },
        "rollback": {
            "policy": "frozen_sft_v1_7",
            "adapter_path": policy["sft_adapter_path"],
            "adapter_sha256": policy["sft_adapter_sha256"],
            "trigger": "any offline gate regression, shadow safety event, or canary SLO breach",
        },
        "production_defaults": dict(production_defaults),
        "required_before_production": [
            "larger human-gold evaluation",
            "untouched final production holdout",
            "shadow traffic with no write-capable tools",
            "canary rollout and tested automatic rollback",
        ],
        "final_holdout_read": False,
    }


def _aggregate(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        raise ValueError("cannot aggregate an empty sequence")
    mean = statistics.fmean(values)
    sample_std = statistics.stdev(values) if len(values) > 1 else 0.0
    critical = _student_t_critical_95(len(values) - 1)
    half_width = critical * sample_std / math.sqrt(len(values)) if len(values) > 1 else 0.0
    return {
        "n": len(values),
        "mean": round(mean, 8),
        "sample_std": round(sample_std, 8),
        "ci95": [round(mean - half_width, 8), round(mean + half_width, 8)],
        "minimum": round(min(values), 8),
        "maximum": round(max(values), 8),
    }


def _student_t_critical_95(degrees_of_freedom: int) -> float:
    table = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262}
    return table.get(degrees_of_freedom, 1.96)


def _bootstrap_delta(values: Sequence[float], *, samples: int, seed: int) -> dict[str, Any]:
    if not values:
        raise ValueError("cannot bootstrap an empty sequence")
    generator = random.Random(seed)
    count = len(values)
    bootstrapped = sorted(
        statistics.fmean(values[generator.randrange(count)] for _ in range(count)) for _ in range(samples)
    )
    lower = bootstrapped[int(samples * 0.025)]
    upper = bootstrapped[min(samples - 1, int(samples * 0.975))]
    return {
        "n": count,
        "observed_delta": round(statistics.fmean(values), 6),
        "ci95": [round(lower, 6), round(upper, 6)],
        "probability_delta_gt_zero": round(sum(value > 0.0 for value in bootstrapped) / samples, 6),
    }


def _load_prediction_rows(path: Path) -> dict[str, Mapping[str, Any]]:
    rows: dict[str, Mapping[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        state_id = str(row["state_id"])
        if int(row.get("sample_index", 0)) != 0:
            raise ValueError("paired Gate expects one deterministic sample per state")
        if state_id in rows:
            raise ValueError(f"duplicate prediction state: {state_id}")
        rows[state_id] = row
    return rows


def _episode_success_by_id(rows: Mapping[str, Mapping[str, Any]]) -> dict[str, bool]:
    episodes: dict[str, list[bool]] = {}
    for row in rows.values():
        episodes.setdefault(str(row["episode_id"]), []).append(_prediction_choice(row))
    return {episode_id: all(values) for episode_id, values in episodes.items()}


def _prediction_reward(row: Mapping[str, Any]) -> float:
    ledger = _mapping(_mapping(row["double_ledger"])["raw"])
    return float(ledger["policy_reward"])


def _prediction_choice(row: Mapping[str, Any]) -> bool:
    components = _mapping(_mapping(_mapping(row["double_ledger"])["raw"])["components"])
    return components.get("tool_choice") == 1.0 and components.get("stop_decision") == 1.0


def _hacking_total(raw_summary: Mapping[str, Any]) -> int:
    return sum(int(value) for value in _mapping(raw_summary.get("reward_hacking_flags", {})).values())


def _correction_total(summary: Mapping[str, Any]) -> int:
    constraint = _mapping(summary.get("constraint", {}))
    return sum(int(value) for value in _mapping(constraint.get("corrections", {})).values())


def _metric(row: Mapping[str, Any], name: str) -> float:
    return float(row.get(name, 0.0))


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _mapping(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"expected mapping, got {type(value).__name__}")
    return value


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object in {path}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--evaluation-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--require-test", action="store_true")
    args = parser.parse_args()
    gate, selection, release = gate_pilot(
        repo_root=args.repo_root.resolve(),
        artifact_root=args.artifact_root.resolve(),
        evaluation_root=args.evaluation_root.resolve(),
    )
    if args.require_test and gate["independent_test"] is None:
        raise SystemExit("independent test evidence is required but missing")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "gate.json": gate,
        "selection_manifest.json": selection,
        "release_rollback_manifest.json": release,
    }
    for name, value in outputs.items():
        (args.output_dir / name).write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(gate, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
