"""Assemble paired, family-level, and resource evidence for SFT ablations."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import fields
from pathlib import Path
from typing import Any, Literal

from .configs import output_dir
from .contract import ControlledPaths, ExperimentSpec
from .statistics import compare_prediction_files

Task = Literal["router", "tutor"]
CORE_STAGES = {
    "router": (
        "router-lr",
        "router-epoch",
        "router-scheduler",
        "router-lora-rank",
        "router-lora-target",
    ),
    "tutor": ("tutor-lr", "tutor-lora"),
}
ATTRIBUTION_CONTROLS = {
    "r-data-scale": "r-data-scale-100pct",
    "r-data-replay": "r-data-replay-00pct",
    "r-data-state": "r-data-state-mixed",
}
EXPECTED_ATTRIBUTION_COUNTS = {
    "r-data-scale": 4,
    "r-data-replay": 4,
    "r-data-state": 3,
    "t-mix": 4,
}
REFERENCE_TELEMETRY = {
    "r-base-engineering-sft-v1-7": "router_2b_v1_7_seed_7703",
    "t-opt-r16-all-lr8e5-e1-cosine": "grounded_tutor_9b_v1_seed_6209",
}


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _spec(value: Mapping[str, Any]) -> ExperimentSpec:
    allowed = {field.name for field in fields(ExperimentSpec)}
    return ExperimentSpec(**{key: value[key] for key in allowed if key in value})


def _spec_key(spec: ExperimentSpec) -> tuple[str, int]:
    return spec.experiment_id, spec.seed


def _registry(paths: ControlledPaths) -> dict[str, Any]:
    return json.loads(paths.experiment_registry.read_text(encoding="utf-8"))


def _all_specs(registry: Mapping[str, Any]) -> list[ExperimentSpec]:
    return [
        _spec(item)
        for section in (
            "initial_experiments",
            "reference_experiments",
            "dynamic_experiments",
        )
        for item in registry.get(section, [])
    ]


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def _evaluation_root(paths: ControlledPaths, spec: ExperimentSpec) -> Path:
    return paths.evaluation_root / spec.experiment_id / str(spec.seed)


def _summary_path(paths: ControlledPaths, spec: ExperimentSpec) -> Path:
    return _evaluation_root(paths, spec) / "sft/raw/summary.json"


def _prediction_path(paths: ControlledPaths, spec: ExperimentSpec) -> Path:
    return _evaluation_root(paths, spec) / "sft/raw/predictions.jsonl"


def _telemetry_path(paths: ControlledPaths, spec: ExperimentSpec) -> Path:
    if spec.reference_adapter_path:
        label = REFERENCE_TELEMETRY[spec.experiment_id]
        return (
            paths.project_root
            / "training_artifacts/studyhub_agent_sft/run_telemetry"
            / label
            / "run_summary.json"
        )
    return (
        paths.training_root
        / "run_telemetry"
        / f"{spec.experiment_id}-seed{spec.seed}"
        / "run_summary.json"
    )


def _adapter_path(paths: ControlledPaths, spec: ExperimentSpec) -> Path:
    return (
        Path(spec.reference_adapter_path)
        if spec.reference_adapter_path
        else output_dir(paths, spec)
    )


def _adapter_bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in path.glob("adapter_model*.safetensors"))


def _resource(paths: ControlledPaths, spec: ExperimentSpec) -> dict[str, Any]:
    telemetry_path = _telemetry_path(paths, spec)
    telemetry = _load_json(telemetry_path)
    gpu = telemetry.get("gpu", {})
    return {
        "telemetry_path": str(telemetry_path),
        "duration_seconds": telemetry.get("duration_seconds"),
        "peak_memory_mib": gpu.get("peak_memory_mib"),
        "mean_power_w": gpu.get("mean_power_w"),
        "exclusive_gpu_observed": gpu.get("exclusive_gpu_observed"),
        "adapter_bytes": _adapter_bytes(_adapter_path(paths, spec)),
        "train_loss": telemetry.get("train_results", {}).get("train_loss"),
        "eval_loss": telemetry.get("eval_results", {}).get("eval_loss"),
        "eval_accuracy": telemetry.get("eval_results", {}).get("eval_accuracy"),
    }


def _metric_rates(summary: Mapping[str, Any]) -> dict[str, float]:
    return {
        str(name): float(value["rate"])
        for name, value in summary.get("metrics", {}).items()
        if value.get("rate") is not None
    }


def _family_rates(
    summary: Mapping[str, Any], *, metric: str
) -> dict[str, float]:
    result: dict[str, float] = {}
    for family, metrics in summary.get("family_metrics", {}).items():
        value = metrics.get(metric, {}).get("rate")
        if value is not None:
            result[str(family)] = float(value)
    return result


def _deltas(
    arm: Mapping[str, float], anchor: Mapping[str, float]
) -> dict[str, float]:
    return {
        key: round(arm[key] - anchor[key], 6)
        for key in sorted(set(arm) & set(anchor))
    }


def attribution_groups(
    *,
    task: Task,
    winner: ExperimentSpec,
    specs: Sequence[ExperimentSpec],
) -> list[dict[str, Any]]:
    """Return the pre-defined one-factor groups and their explicit controls."""

    if task == "router":
        result = []
        for stage, control_id in ATTRIBUTION_CONTROLS.items():
            candidates = [item for item in specs if item.stage == stage]
            controls = [item for item in candidates if item.experiment_id == control_id]
            if len(candidates) != EXPECTED_ATTRIBUTION_COUNTS[stage]:
                raise ValueError(
                    f"{stage} has {len(candidates)} arms; "
                    f"expected {EXPECTED_ATTRIBUTION_COUNTS[stage]}"
                )
            if len(controls) != 1:
                raise ValueError(f"{stage} requires exactly one control: {control_id}")
            result.append(
                {"stage": stage, "anchor": controls[0], "candidates": candidates}
            )
        return result

    candidates = [winner, *(item for item in specs if item.stage == "t-mix")]
    if len(candidates) != EXPECTED_ATTRIBUTION_COUNTS["t-mix"]:
        raise ValueError(
            f"t-mix has {len(candidates)} arms including the frozen winner; "
            f"expected {EXPECTED_ATTRIBUTION_COUNTS['t-mix']}"
        )
    return [{"stage": "t-mix", "anchor": winner, "candidates": candidates}]


def _core_groups(
    *, task: Task, registry: Mapping[str, Any]
) -> list[dict[str, Any]]:
    expected = set(CORE_STAGES[task])
    groups: list[dict[str, Any]] = []
    events = [
        item
        for item in registry.get("selection_events", [])
        if str(item.get("stage")) in expected
    ]
    counts = {stage: 0 for stage in expected}
    for event in events:
        counts[str(event.get("stage"))] += 1
    invalid_counts = {stage: count for stage, count in counts.items() if count != 1}
    if invalid_counts:
        raise ValueError(
            f"{task} core selection stages require exactly one event: {invalid_counts}"
        )
    for event in events:
        stage = str(event["stage"])
        selected = [_spec(item) for item in event.get("selected", [])]
        candidates = [
            _spec(item["spec"]) for item in event.get("candidates", [])
        ]
        if not selected or not candidates:
            raise ValueError(f"selection event {stage} has no selected anchor or candidates")
        groups.append(
            {
                "stage": stage,
                "anchor": selected[0],
                "candidates": candidates,
                "selection_rule": event.get("rule"),
                "selected": [item.to_dict() for item in selected],
                "selected_at": event.get("at"),
            }
        )
    found = {item["stage"] for item in groups}
    if found != expected:
        raise ValueError(
            f"{task} core selection stages are incomplete: "
            f"missing={sorted(expected - found)}, unexpected={sorted(found - expected)}"
        )
    return groups


def _group_result(
    *,
    paths: ControlledPaths,
    task: Task,
    group: Mapping[str, Any],
) -> dict[str, Any]:
    metric = "strict_route_pass" if task == "router" else "strict_grounded_pass"
    anchor = group["anchor"]
    candidates = group["candidates"]
    anchor_summary = _load_json(_summary_path(paths, anchor))
    anchor_metrics = _metric_rates(anchor_summary)
    anchor_families = _family_rates(anchor_summary, metric=metric)
    anchor_resource = _resource(paths, anchor)
    arms: list[dict[str, Any]] = []
    for spec in candidates:
        summary = _load_json(_summary_path(paths, spec))
        gate = _load_json(_evaluation_root(paths, spec) / "gate.json")
        metrics = _metric_rates(summary)
        families = _family_rates(summary, metric=metric)
        resource = _resource(paths, spec)
        comparison = None
        if _spec_key(spec) != _spec_key(anchor):
            comparison = compare_prediction_files(
                baseline_path=_prediction_path(paths, anchor),
                candidate_path=_prediction_path(paths, spec),
                metric=metric,
            )
        arms.append(
            {
                "spec": spec.to_dict(),
                "is_anchor": _spec_key(spec) == _spec_key(anchor),
                "gate_passed": bool(gate.get("passed")),
                "screening_eligible": bool(gate.get("screening_eligible")),
                "selection_score": gate.get("selection_score"),
                "gate_failures": gate.get("failures", {}),
                "metrics": metrics,
                "metric_delta_vs_anchor": _deltas(metrics, anchor_metrics),
                "family_primary": families,
                "family_primary_delta_vs_anchor": _deltas(
                    families, anchor_families
                ),
                "paired_primary_vs_anchor": comparison,
                "resources": resource,
            }
        )
    resource_comparable = all(
        item["resources"]["exclusive_gpu_observed"] is True for item in arms
    )
    return {
        "stage": group["stage"],
        "primary_metric": metric,
        "anchor": anchor.to_dict(),
        "selection_rule": group.get("selection_rule"),
        "selected": group.get("selected"),
        "selected_at": group.get("selected_at"),
        "resource_comparison_valid": resource_comparable,
        "resource_policy": (
            "compare duration and memory only when every arm observed exclusive GPU use"
        ),
        "anchor_resources": anchor_resource,
        "arms": arms,
    }


def build_ablation_index(
    *,
    task: Task,
    experiment_id: str,
    seed: int,
    paths: ControlledPaths | None = None,
) -> dict[str, Any]:
    paths = paths or ControlledPaths()
    registry = _registry(paths)
    specs = _all_specs(registry)
    winners = [
        item
        for item in specs
        if item.experiment_id == experiment_id and item.seed == seed
    ]
    if len(winners) != 1:
        raise ValueError(
            f"expected one winner {experiment_id}/seed={seed}, found {len(winners)}"
        )
    winner = winners[0]
    if winner.task != task:
        raise ValueError(f"winner task is {winner.task}, requested task is {task}")
    groups = [
        *_core_groups(task=task, registry=registry),
        *attribution_groups(task=task, winner=winner, specs=specs),
    ]
    result = {
        "schema_version": "studyhub.agent.sft.controlled_v2.ablation_index.v1",
        "task": task,
        "winner_before_attribution": winner.to_dict(),
        "interpretation_policy": (
            "Core groups support selection; attribution groups explain one-factor "
            "effects and do not retroactively select on sealed data."
        ),
        "sealed_data_read": False,
        "groups": [
            _group_result(paths=paths, task=task, group=group) for group in groups
        ],
    }
    destination = paths.evaluation_root / "ablation" / task / "ablation_index.json"
    _write_json(destination, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", choices=("router", "tutor"))
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args()
    result = build_ablation_index(
        task=args.task,
        experiment_id=args.experiment_id,
        seed=args.seed,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
