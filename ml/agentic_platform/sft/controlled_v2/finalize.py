"""Assemble the controlled SFT evidence after a winner has three seed runs."""

from __future__ import annotations

import argparse
import json
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import fields
from pathlib import Path
from typing import Any, Literal

from ..spec import load_jsonl, sha256_file
from .configs import output_dir
from .contract import (
    ROUTER_GATE,
    ROUTER_SEEDS,
    TUTOR_GATE,
    TUTOR_SEEDS,
    ControlledPaths,
    ExperimentSpec,
)
from .statistics import compare_prediction_files, summarize_seeds

Task = Literal["router", "tutor"]
ROUTER_LEGACY_FAMILIES = frozenset(
    {
        "direct_final_replay_v1_7",
        "search_replay_v1_7",
        "permission_refusal_replay_v1_7",
        "material_id_replay_v1_7",
        "explicit_page_replay_v1_7",
        "force_final_replay_v1_7",
    }
)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _spec(value: Mapping[str, Any]) -> ExperimentSpec:
    allowed = {field.name for field in fields(ExperimentSpec)}
    return ExperimentSpec(**{key: value[key] for key in allowed if key in value})


def _registry_specs(paths: ControlledPaths) -> list[ExperimentSpec]:
    registry = json.loads(paths.experiment_registry.read_text(encoding="utf-8"))
    return [
        _spec(item)
        for section in (
            "initial_experiments",
            "reference_experiments",
            "dynamic_experiments",
        )
        for item in registry.get(section, [])
    ]


def _winner_specs(
    *, paths: ControlledPaths, task: Task, experiment_id: str
) -> list[ExperimentSpec]:
    expected = set(ROUTER_SEEDS if task == "router" else TUTOR_SEEDS)
    specs = [
        item
        for item in _registry_specs(paths)
        if item.task == task
        and item.experiment_id == experiment_id
        and item.seed in expected
    ]
    by_seed = {item.seed: item for item in specs}
    if set(by_seed) != expected:
        raise ValueError(
            f"{experiment_id} has seeds {sorted(by_seed)}, expected {sorted(expected)}"
        )
    canonical = next(iter(by_seed.values()))
    controlled_fields = (
        "learning_rate",
        "epochs",
        "lora_rank",
        "lora_target",
        "scheduler",
        "dataset_variant",
        "max_steps",
    )
    for item in by_seed.values():
        changed = [
            field
            for field in controlled_fields
            if getattr(item, field) != getattr(canonical, field)
        ]
        if changed:
            raise ValueError(
                f"seed {item.seed} changes controlled fields: {', '.join(changed)}"
            )
    return [by_seed[seed] for seed in sorted(expected)]


def _summary_path(
    paths: ControlledPaths, spec: ExperimentSpec, *, condition: str = "sft"
) -> Path:
    return (
        paths.evaluation_root
        / spec.experiment_id
        / str(spec.seed)
        / condition
        / "raw/summary.json"
    )


def _prediction_path(
    paths: ControlledPaths, spec: ExperimentSpec, *, condition: str = "sft"
) -> Path:
    return (
        paths.evaluation_root
        / spec.experiment_id
        / str(spec.seed)
        / condition
        / "raw/predictions.jsonl"
    )


def _gate_path(paths: ControlledPaths, spec: ExperimentSpec) -> Path:
    return paths.evaluation_root / spec.experiment_id / str(spec.seed) / "gate.json"


def _load_required(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def _subset_rate(path: Path, *, metric: str, families: set[str]) -> float:
    values = [
        bool(row["scores"][metric])
        for row in load_jsonl(path)
        if str(row["task_family"]) in families
        and row.get("scores", {}).get(metric) is not None
    ]
    if not values:
        raise ValueError(f"no scored rows for {sorted(families)} in {path}")
    return sum(values) / len(values)


def _reference_spec(paths: ControlledPaths, task: Task) -> ExperimentSpec:
    reference_id = (
        "r-base-engineering-sft-v1-7"
        if task == "router"
        else "t-opt-r16-all-lr8e5-e1-cosine"
    )
    matches = [
        item
        for item in _registry_specs(paths)
        if item.task == task and item.experiment_id == reference_id
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one {task} reference, found {len(matches)}")
    return matches[0]


def _regression_summary(
    *,
    paths: ControlledPaths,
    task: Task,
    winner_specs: Sequence[ExperimentSpec],
) -> dict[str, Any]:
    reference = _reference_spec(paths, task)
    reference_predictions = _prediction_path(paths, reference)
    if task == "router":
        families = set(ROUTER_LEGACY_FAMILIES)
        threshold_pp = float(ROUTER_GATE["legacy_regression_pp_max"])
        label = "legacy_router_families"
        metric = "strict_route_pass"
    else:
        families = {"normal_answer_v2"}
        threshold_pp = float(TUTOR_GATE["normal_answer_regression_pp_max"])
        label = "normal_answer_v2"
        metric = "strict_grounded_pass"
    reference_rate = _subset_rate(
        reference_predictions, metric=metric, families=families
    )
    seed_rates = [
        {
            "seed": spec.seed,
            "rate": _subset_rate(
                _prediction_path(paths, spec), metric=metric, families=families
            ),
        }
        for spec in winner_specs
    ]
    worst_rate = min(float(item["rate"]) for item in seed_rates)
    regression_pp = max(0.0, reference_rate - worst_rate) * 100
    return {
        "subset": label,
        "families": sorted(families),
        "metric": metric,
        "reference_experiment_id": reference.experiment_id,
        "reference_seed": reference.seed,
        "reference_rate": round(reference_rate, 6),
        "candidate_seed_rates": seed_rates,
        "candidate_worst_seed_rate": round(worst_rate, 6),
        "regression_pp": round(regression_pp, 6),
        "threshold_pp_max": threshold_pp,
        "passed": regression_pp <= threshold_pp,
    }


def _adapter_bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in path.glob("adapter_model*.safetensors"))


def _resource_summary(
    paths: ControlledPaths, specs: Sequence[ExperimentSpec]
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for spec in specs:
        if spec.reference_adapter_path:
            adapter = Path(spec.reference_adapter_path)
            reference_labels = {
                "r-base-engineering-sft-v1-7": "router_2b_v1_7_seed_7703",
                "t-opt-r16-all-lr8e5-e1-cosine": ("grounded_tutor_9b_v1_seed_6209"),
            }
            telemetry_path = (
                paths.project_root
                / "training_artifacts/studyhub_agent_sft/run_telemetry"
                / reference_labels[spec.experiment_id]
                / "run_summary.json"
            )
        else:
            adapter = output_dir(paths, spec)
            telemetry_path = (
                paths.training_root
                / "run_telemetry"
                / f"{spec.experiment_id}-seed{spec.seed}"
                / "run_summary.json"
            )
        telemetry = _load_required(telemetry_path)
        rows.append(
            {
                "seed": spec.seed,
                "duration_seconds": telemetry["duration_seconds"],
                "peak_memory_mib": telemetry["gpu"]["peak_memory_mib"],
                "mean_power_w": telemetry["gpu"]["mean_power_w"],
                "train_loss": telemetry.get("train_results", {}).get("train_loss"),
                "eval_loss": telemetry.get("eval_results", {}).get("eval_loss"),
                "adapter_bytes": _adapter_bytes(adapter),
                "adapter_path": str(adapter),
            }
        )
    return {
        "per_seed": rows,
        "duration_seconds_mean": round(
            statistics.fmean(float(item["duration_seconds"]) for item in rows), 3
        ),
        "peak_memory_mib_max": max(float(item["peak_memory_mib"]) for item in rows),
        "adapter_bytes": sorted({int(item["adapter_bytes"]) for item in rows}),
    }


def _paired_comparisons(
    *,
    paths: ControlledPaths,
    task: Task,
    candidate: ExperimentSpec,
) -> dict[str, Any]:
    metric = "strict_route_pass" if task == "router" else "strict_grounded_pass"
    candidate_path = _prediction_path(paths, candidate)
    baseline_root = paths.evaluation_root / "baselines" / task / "qwen35_base"
    comparisons: dict[str, Any] = {}
    for condition in ("base", "prompt", "few_shot"):
        baseline_path = baseline_root / condition / "raw/predictions.jsonl"
        comparisons[condition] = compare_prediction_files(
            baseline_path=baseline_path,
            candidate_path=candidate_path,
            metric=metric,
        )
    reference = _reference_spec(paths, task)
    comparisons["completed_sft_reference"] = compare_prediction_files(
        baseline_path=_prediction_path(paths, reference),
        candidate_path=candidate_path,
        metric=metric,
    )
    return comparisons


def finalize_winner(
    *,
    task: Task,
    experiment_id: str,
    paths: ControlledPaths | None = None,
) -> dict[str, Any]:
    paths = paths or ControlledPaths()
    specs = _winner_specs(paths=paths, task=task, experiment_id=experiment_id)
    metric = "strict_route_pass" if task == "router" else "strict_grounded_pass"
    expected_seeds = ROUTER_SEEDS if task == "router" else TUTOR_SEEDS
    summaries = [_load_required(_summary_path(paths, spec)) for spec in specs]
    seed_summary = summarize_seeds(
        summaries, metric=metric, expected_seeds=expected_seeds
    )
    gates = [_load_required(_gate_path(paths, spec)) for spec in specs]
    per_seed_passed = all(bool(gate.get("passed")) for gate in gates)
    std_threshold = float(
        (ROUTER_GATE if task == "router" else TUTOR_GATE)["cross_seed_primary_std_max"]
    )
    std_passed = float(seed_summary["std"]) <= std_threshold
    regression = _regression_summary(paths=paths, task=task, winner_specs=specs)
    median_seed = int(seed_summary["median_seed"])
    median_spec = next(item for item in specs if item.seed == median_seed)
    comparisons = _paired_comparisons(paths=paths, task=task, candidate=median_spec)
    result = {
        "schema_version": "studyhub.agent.sft.controlled_v2.final_decision.v1",
        "task": task,
        "experiment_id": experiment_id,
        "configuration": {
            key: getattr(median_spec, key)
            for key in (
                "learning_rate",
                "epochs",
                "lora_rank",
                "lora_target",
                "scheduler",
                "dataset_variant",
                "max_steps",
            )
        },
        "seed_summary": seed_summary,
        "delivery_seed_rule": "development primary metric median seed",
        "delivery_seed": median_seed,
        "per_seed_gates": [
            {
                "seed": spec.seed,
                "passed": bool(gate.get("passed")),
                "selection_score": gate.get("selection_score"),
                "failures": gate.get("failures", {}),
                "gate_sha256": sha256_file(_gate_path(paths, spec)),
            }
            for spec, gate in zip(specs, gates, strict=True)
        ],
        "cross_seed_gate": {
            "actual_std": seed_summary["std"],
            "threshold_max": std_threshold,
            "passed": std_passed,
        },
        "regression_gate": regression,
        "paired_comparisons": comparisons,
        "resources": _resource_summary(paths, specs),
        "sealed_data_read": False,
        "passed": per_seed_passed and std_passed and bool(regression["passed"]),
    }
    root = paths.evaluation_root / "final" / task
    _write_json(root / "final_decision.json", result)
    for label, comparison in comparisons.items():
        _write_json(root / "paired_statistics" / f"{label}_vs_winner.json", comparison)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", choices=("router", "tutor"))
    parser.add_argument("--experiment-id", required=True)
    args = parser.parse_args()
    result = finalize_winner(task=args.task, experiment_id=args.experiment_id)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
