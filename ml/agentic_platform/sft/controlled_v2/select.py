"""Deterministic stage advancement from development Gate artifacts only."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import fields
from pathlib import Path
from typing import Any

from ..spec import load_jsonl
from .contract import (
    ControlledPaths,
    ExperimentSpec,
    lora_rank_experiments,
    router_epoch_experiments,
    router_lora_target_experiment,
    router_scheduler_experiment,
    seed_experiments,
)
from .registry import record_selection, register_specs

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
REFERENCE_EXPERIMENTS = {
    "router": ("r-base-engineering-sft-v1-7", 7703),
    "tutor": ("t-opt-r16-all-lr8e5-e1-cosine", 6209),
}
REFERENCE_TELEMETRY = {
    "router": "router_2b_v1_7_seed_7703",
    "tutor": "grounded_tutor_9b_v1_seed_6209",
}


def _spec(value: Mapping[str, Any]) -> ExperimentSpec:
    allowed = {field.name for field in fields(ExperimentSpec)}
    return ExperimentSpec(**{key: value[key] for key in allowed if key in value})


def _all_specs(paths: ControlledPaths) -> list[ExperimentSpec]:
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


def _gate(paths: ControlledPaths, spec: ExperimentSpec) -> dict[str, Any]:
    path = paths.evaluation_root / spec.experiment_id / str(spec.seed) / "gate.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"development Gate is missing for {spec.experiment_id}/seed={spec.seed}"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _predictions_path(paths: ControlledPaths, spec: ExperimentSpec) -> Path:
    return (
        paths.evaluation_root
        / spec.experiment_id
        / str(spec.seed)
        / "sft/raw/predictions.jsonl"
    )


def _summary(paths: ControlledPaths, spec: ExperimentSpec) -> dict[str, Any]:
    path = _predictions_path(paths, spec).with_name("summary.json")
    if not path.is_file():
        raise FileNotFoundError(f"development summary is missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _reference_spec(paths: ControlledPaths, task: str) -> ExperimentSpec:
    experiment_id, seed = REFERENCE_EXPERIMENTS[task]
    matches = [
        item
        for item in _all_specs(paths)
        if item.experiment_id == experiment_id and item.seed == seed
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one {task} completed-SFT reference")
    return matches[0]


def _subset_rate(path: Path, *, task: str) -> float:
    metric = "strict_route_pass" if task == "router" else "strict_grounded_pass"
    values = [
        bool(row["scores"][metric])
        for row in load_jsonl(path)
        if (
            str(row["task_family"]) in ROUTER_LEGACY_FAMILIES
            if task == "router"
            else str(row["task_family"]) == "normal_answer_v2"
        )
        and row.get("scores", {}).get(metric) is not None
    ]
    if not values:
        raise ValueError(f"no {task} regression anchors in {path}")
    return sum(values) / len(values)


def _family_floor(summary: Mapping[str, Any], *, task: str) -> float:
    if task == "router":
        return float(summary.get("task_family_floor") or 0.0)
    rates = [
        float(metrics["strict_grounded_pass"]["rate"] or 0.0)
        for metrics in summary.get("family_metrics", {}).values()
    ]
    return min(rates, default=0.0)


def _resource_cost(
    paths: ControlledPaths, spec: ExperimentSpec
) -> dict[str, float | str]:
    if spec.reference_adapter_path:
        path = (
            paths.project_root
            / "training_artifacts/studyhub_agent_sft/run_telemetry"
            / REFERENCE_TELEMETRY[spec.task]
            / "run_summary.json"
        )
    else:
        path = (
            paths.training_root
            / "run_telemetry"
            / f"{spec.experiment_id}-seed{spec.seed}"
            / "run_summary.json"
        )
    if not path.is_file():
        raise FileNotFoundError(f"training telemetry is missing: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    return {
        "peak_memory_mib": float(value["gpu"]["peak_memory_mib"]),
        "duration_seconds": float(value["duration_seconds"]),
        "exclusive_gpu_observed": value["gpu"].get("exclusive_gpu_observed"),
        "path": str(path),
    }


def rank_candidates(
    specs: Sequence[ExperimentSpec], *, paths: ControlledPaths
) -> list[dict[str, Any]]:
    if not specs:
        raise ValueError("candidate list is empty")
    tasks = {item.task for item in specs}
    if len(tasks) != 1:
        raise ValueError(f"candidate list mixes tasks: {sorted(tasks)}")
    task = next(iter(tasks))
    reference = _reference_spec(paths, task)
    reference_predictions = _predictions_path(paths, reference)
    if not reference_predictions.is_file():
        raise FileNotFoundError(
            f"completed-SFT reference evaluation is missing: {reference_predictions}"
        )
    reference_rate = _subset_rate(reference_predictions, task=task)
    candidates: list[dict[str, Any]] = []
    for spec in specs:
        gate = _gate(paths, spec)
        summary = _summary(paths, spec)
        candidate_rate = _subset_rate(_predictions_path(paths, spec), task=task)
        regression_pp = max(0.0, reference_rate - candidate_rate) * 100
        regression_passed = regression_pp <= 1.0
        resource = _resource_cost(paths, spec)
        candidates.append(
            {
                "spec": spec,
                "screening_eligible": bool(gate.get("screening_eligible"))
                and regression_passed,
                "safety_eligible": bool(gate.get("screening_eligible")),
                "regression": {
                    "reference_rate": round(reference_rate, 6),
                    "candidate_rate": round(candidate_rate, 6),
                    "regression_pp": round(regression_pp, 6),
                    "threshold_pp_max": 1.0,
                    "passed": regression_passed,
                },
                "family_floor": _family_floor(summary, task=task),
                "resource_cost": resource,
                "full_gate_passed": bool(gate.get("passed")),
                "selection_score": float(gate.get("selection_score") or 0.0),
                "failures": gate.get("failures", {}),
            }
        )
    resource_comparable = all(
        item["resource_cost"]["exclusive_gpu_observed"] is True
        for item in candidates
    )
    for item in candidates:
        item["resource_tiebreak_used"] = resource_comparable
    return sorted(
        candidates,
        key=lambda item: (
            not item["screening_eligible"],
            -item["selection_score"],
            -item["family_floor"],
            item["regression"]["regression_pp"],
            item["resource_cost"]["peak_memory_mib"] if resource_comparable else 0.0,
            item["resource_cost"]["duration_seconds"] if resource_comparable else 0.0,
            item["spec"].experiment_id,
            item["spec"].seed,
        ),
    )


def _eligible_top(
    ranked: Sequence[Mapping[str, Any]], count: int, *, allow_fewer: bool = False
) -> list[ExperimentSpec]:
    eligible = [item for item in ranked if item["screening_eligible"]]
    required = 1 if allow_fewer else count
    if len(eligible) < required:
        raise RuntimeError(
            f"only {len(eligible)} candidates pass the screening safety Gate; "
            f"{required} required"
        )
    return [item["spec"] for item in eligible[:count]]


def _candidate_manifest(ranked: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "spec": item["spec"].to_dict(),
            "screening_eligible": item["screening_eligible"],
            "safety_eligible": item["safety_eligible"],
            "regression": item["regression"],
            "family_floor": item["family_floor"],
            "resource_cost": item["resource_cost"],
            "resource_tiebreak_used": item["resource_tiebreak_used"],
            "full_gate_passed": item["full_gate_passed"],
            "selection_score": item["selection_score"],
            "failures": item["failures"],
        }
        for item in ranked
    ]


def _router_epoch_candidates(
    specs: Sequence[ExperimentSpec],
) -> list[ExperimentSpec]:
    epoch_specs = [item for item in specs if item.stage == "r-opt-epoch"]
    selected_rates = {item.learning_rate for item in epoch_specs}
    if not selected_rates:
        raise ValueError("Router epoch stage has no admitted learning rates")
    return [
        item
        for item in specs
        if item.stage == "r-opt-epoch"
        or (item.stage == "r-opt-lr" and item.learning_rate in selected_rates)
    ]


def advance(
    stage: str, *, paths: ControlledPaths | None = None
) -> list[ExperimentSpec]:
    paths = paths or ControlledPaths()
    specs = _all_specs(paths)
    if stage == "router-lr":
        candidates = [item for item in specs if item.stage == "r-opt-lr"]
        ranked = rank_candidates(candidates, paths=paths)
        selected = _eligible_top(ranked, 2, allow_fewer=True)
        created = list(
            router_epoch_experiments(tuple(item.learning_rate for item in selected))
        )
    elif stage == "router-epoch":
        candidates = _router_epoch_candidates(specs)
        ranked = rank_candidates(candidates, paths=paths)
        selected = _eligible_top(ranked, 1)
        created = [router_scheduler_experiment(selected[0])]
    elif stage == "router-scheduler":
        scheduler_specs = [item for item in specs if item.stage == "r-opt-scheduler"]
        if len(scheduler_specs) != 1:
            raise RuntimeError("Router scheduler stage expects exactly one linear arm")
        parent_id = scheduler_specs[0].parent_experiment_id
        parent = [
            item
            for item in specs
            if item.experiment_id == parent_id and item.seed == scheduler_specs[0].seed
        ]
        candidates = [*parent, *scheduler_specs]
        ranked = rank_candidates(candidates, paths=paths)
        selected = _eligible_top(ranked, 1)
        created = list(lora_rank_experiments(selected[0]))
    elif stage == "router-lora-rank":
        lora_specs = [item for item in specs if item.stage == "r-lora-rank"]
        parent_ids = {item.parent_experiment_id for item in lora_specs}
        parent = [item for item in specs if item.experiment_id in parent_ids]
        candidates = [*parent, *lora_specs]
        ranked = rank_candidates(candidates, paths=paths)
        selected = _eligible_top(ranked, 1)
        created = [router_lora_target_experiment(selected[0])]
    elif stage == "router-lora-target":
        target_specs = [item for item in specs if item.stage == "r-lora-target"]
        if len(target_specs) != 1:
            raise RuntimeError("Router target stage expects exactly one attention-only arm")
        parent_id = target_specs[0].parent_experiment_id
        parent = [
            item
            for item in specs
            if item.experiment_id == parent_id and item.seed == target_specs[0].seed
        ]
        candidates = [*parent, *target_specs]
        ranked = rank_candidates(candidates, paths=paths)
        selected = _eligible_top(ranked, 1)
        created = list(seed_experiments(selected[0]))
    elif stage == "tutor-lr":
        candidates = [
            item for item in specs if item.stage in {"t-opt-lr", "t-opt-reference"}
        ]
        ranked = rank_candidates(candidates, paths=paths)
        selected = _eligible_top(ranked, 1)
        created = list(lora_rank_experiments(selected[0]))
    elif stage == "tutor-lora":
        lora_specs = [item for item in specs if item.stage == "t-lora-rank"]
        parent_ids = {item.parent_experiment_id for item in lora_specs}
        parent = [item for item in specs if item.experiment_id in parent_ids]
        candidates = [*parent, *lora_specs]
        ranked = rank_candidates(candidates, paths=paths)
        selected = _eligible_top(ranked, 1)
        created = list(seed_experiments(selected[0]))
    else:
        raise ValueError(f"unsupported selection stage: {stage}")

    record_selection(
        stage=stage,
        candidates=_candidate_manifest(ranked),
        selected=selected,
        rule=(
            "Safety and <=1 pp regression hard constraints; descending primary raw "
            "score and family floor; then lower peak memory and duration; "
            "deterministic experiment ID tie-break."
        ),
        paths=paths,
    )
    register_specs(
        created,
        paths=paths,
        reason=f"Created by controlled-v2 stage selection: {stage}",
    )
    return created


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "stage",
        choices=(
            "router-lr",
            "router-epoch",
            "router-scheduler",
            "router-lora-rank",
            "router-lora-target",
            "tutor-lr",
            "tutor-lora",
        ),
    )
    args = parser.parse_args()
    result = advance(args.stage)
    print(
        json.dumps(
            [item.to_dict() for item in result],
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
