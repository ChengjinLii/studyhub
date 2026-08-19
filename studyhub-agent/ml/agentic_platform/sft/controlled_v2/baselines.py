"""Run paired Base, strong Prompt, Few-shot, and completed-SFT references."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Literal

from ..spec import load_jsonl, sha256_file
from .configs import ROUTER_MODEL, TUTOR_MODEL
from .contract import ControlledPaths
from .evaluate import evaluate_router_conditions, evaluate_tutor_conditions
from .run import resolve_spec, run_experiment
from .statistics import compare_prediction_files


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _artifact(path: Path, *, records: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "path": str(path),
        "sha256": sha256_file(path),
    }
    if records is not None:
        result["records"] = records
    return result


def _condition_artifacts(
    *,
    task: Literal["router", "tutor"],
    condition: str,
    baseline_root: Path,
    dataset_path: Path,
    few_shot_path: Path,
) -> dict[str, Any] | None:
    condition_root = baseline_root / condition
    files = {
        "raw_predictions": condition_root / "raw/predictions.jsonl",
        "raw_summary": condition_root / "raw/summary.json",
    }
    if task == "router":
        files.update(
            {
                "normalized_predictions": condition_root
                / "normalized/predictions.jsonl",
                "normalized_summary": condition_root / "normalized/summary.json",
                "projection_comparison": condition_root
                / "projection_comparison.json",
            }
        )
    if not all(path.is_file() for path in files.values()):
        return None
    try:
        expected_rows = load_jsonl(dataset_path)
        expected_ids = [str(row["example_id"]) for row in expected_rows]
        raw_rows = load_jsonl(files["raw_predictions"])
        raw_summary = json.loads(files["raw_summary"].read_text(encoding="utf-8"))
        summaries = [raw_summary]
        prediction_rows = {"raw_predictions": raw_rows}
        if task == "router":
            normalized_rows = load_jsonl(files["normalized_predictions"])
            normalized_summary = json.loads(
                files["normalized_summary"].read_text(encoding="utf-8")
            )
            projection = json.loads(
                files["projection_comparison"].read_text(encoding="utf-8")
            )
            summaries.append(normalized_summary)
            prediction_rows["normalized_predictions"] = normalized_rows
            if int(projection.get("records", -1)) != len(expected_rows):
                return None
        expected_contract = {
            "dataset_sha256": sha256_file(dataset_path),
            "few_shot_sha256": sha256_file(few_shot_path),
        }
        if any(
            summary.get("task") != task
            or summary.get("condition") != condition
            or int(summary.get("records", -1)) != len(expected_rows)
            or any(
                summary.get("input_contract", {}).get(key) != value
                for key, value in expected_contract.items()
            )
            for summary in summaries
        ):
            return None
        if any(
            [str(row.get("example_id")) for row in rows] != expected_ids
            for rows in prediction_rows.values()
        ):
            return None
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError):
        return None

    return {
        name: _artifact(
            path,
            records=(len(prediction_rows[name]) if name in prediction_rows else None),
        )
        for name, path in files.items()
    }


def run_baselines(
    task: Literal["router", "tutor"],
    *,
    gpu: int,
    paths: ControlledPaths | None = None,
) -> dict[str, Any]:
    paths = paths or ControlledPaths()
    os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu)
    baseline_root = paths.evaluation_root / "baselines" / task / "qwen35_base"
    dataset_path = paths.router_challenge if task == "router" else paths.tutor_challenge
    few_shot_path = paths.router_few_shot if task == "router" else paths.tutor_few_shot
    pending = tuple(
        condition
        for condition in ("base", "prompt", "few_shot")
        if _condition_artifacts(
            task=task,
            condition=condition,
            baseline_root=baseline_root,
            dataset_path=dataset_path,
            few_shot_path=few_shot_path,
        )
        is None
    )
    if pending:
        if task == "router":
            evaluate_router_conditions(
                model_path=ROUTER_MODEL,
                adapter_path=None,
                dataset_path=dataset_path,
                few_shot_path=few_shot_path,
                output_root=baseline_root,
                conditions=pending,
            )
        else:
            evaluate_tutor_conditions(
                model_path=TUTOR_MODEL,
                adapter_path=None,
                dataset_path=dataset_path,
                few_shot_path=few_shot_path,
                output_root=baseline_root,
                conditions=pending,
            )

    if task == "router":
        reference_id, seed, metric = (
            "r-base-engineering-sft-v1-7",
            7703,
            "strict_route_pass",
        )
        suffix = Path("sft/raw/predictions.jsonl")
    else:
        reference_id, seed, metric = (
            "t-opt-r16-all-lr8e5-e1-cosine",
            6209,
            "strict_grounded_pass",
        )
        suffix = Path("sft/raw/predictions.jsonl")
    reference = resolve_spec(paths=paths, experiment_id=reference_id, seed=seed)
    run_experiment(
        paths=paths,
        spec=reference,
        gpu=gpu,
        train=False,
        evaluate=True,
    )
    reference_predictions = paths.evaluation_root / reference_id / str(seed) / suffix
    reference_root = paths.evaluation_root / reference_id / str(seed)
    comparisons: dict[str, Any] = {}
    comparison_artifacts: dict[str, Any] = {}
    for condition in ("base", "prompt", "few_shot"):
        baseline_predictions = baseline_root / condition / "raw/predictions.jsonl"
        result = compare_prediction_files(
            baseline_path=baseline_predictions,
            candidate_path=reference_predictions,
            metric=metric,
        )
        output = (
            paths.evaluation_root
            / "baselines"
            / task
            / f"{condition}_vs_sft"
            / "paired_statistics.json"
        )
        _write_json(output, result)
        comparisons[condition] = result
        comparison_artifacts[condition] = _artifact(output)
    condition_artifacts = {
        condition: _condition_artifacts(
            task=task,
            condition=condition,
            baseline_root=baseline_root,
            dataset_path=dataset_path,
            few_shot_path=few_shot_path,
        )
        for condition in ("base", "prompt", "few_shot")
    }
    if any(value is None for value in condition_artifacts.values()):
        raise RuntimeError(f"{task} baseline condition artifacts are incomplete")
    reference_summary = reference_root / "sft/raw/summary.json"
    reference_gate = reference_root / "gate.json"
    if not all(
        path.is_file()
        for path in (reference_predictions, reference_summary, reference_gate)
    ):
        raise RuntimeError(f"{task} completed-SFT reference artifacts are incomplete")
    reference_rows = load_jsonl(reference_predictions)
    expected_ids = [str(row["example_id"]) for row in load_jsonl(dataset_path)]
    if [str(row.get("example_id")) for row in reference_rows] != expected_ids:
        raise RuntimeError(
            f"{task} completed-SFT reference does not match the frozen challenge"
        )
    index = {
        "schema_version": "studyhub.agent.sft.controlled_v2.baselines.v2",
        "task": task,
        "conditions": ["base", "prompt", "few_shot", "sft"],
        "reference_experiment_id": reference_id,
        "reference_seed": seed,
        "metric": metric,
        "paired_comparisons": comparisons,
        "condition_artifacts": condition_artifacts,
        "reference_artifacts": {
            "predictions": _artifact(
                reference_predictions, records=len(reference_rows)
            ),
            "summary": _artifact(reference_summary),
            "gate": _artifact(reference_gate),
        },
        "paired_comparison_artifacts": comparison_artifacts,
    }
    _write_json(
        paths.evaluation_root / "baselines" / task / "baseline_index.json", index
    )
    return index


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", choices=("router", "tutor"))
    parser.add_argument("--gpu", type=int, required=True, choices=(0, 1))
    args = parser.parse_args()
    result = run_baselines(args.task, gpu=args.gpu)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
