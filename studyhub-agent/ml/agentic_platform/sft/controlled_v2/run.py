"""Resumable single-arm runner for controlled-v2 training, evaluation, and Gate."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from collections.abc import Mapping
from dataclasses import fields
from pathlib import Path
from typing import Any

from ..spec import sha256_file
from .configs import config_path, generate_configs, output_dir
from .contract import ControlledPaths, ExperimentSpec
from .evaluate import evaluate_router_conditions, evaluate_tutor_conditions
from .gates import gate_router, gate_tutor


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _spec_from_dict(value: Mapping[str, Any]) -> ExperimentSpec:
    allowed = {field.name for field in fields(ExperimentSpec)}
    return ExperimentSpec(**{key: value[key] for key in allowed if key in value})


def resolve_spec(
    *, paths: ControlledPaths, experiment_id: str, seed: int
) -> ExperimentSpec:
    registry = json.loads(paths.experiment_registry.read_text(encoding="utf-8"))
    candidates = [
        _spec_from_dict(item)
        for section in (
            "initial_experiments",
            "reference_experiments",
            "dynamic_experiments",
        )
        for item in registry.get(section, [])
        if item.get("experiment_id") == experiment_id and int(item.get("seed")) == seed
    ]
    if len(candidates) != 1:
        raise ValueError(
            f"expected one registered spec for {experiment_id}/seed={seed}, "
            f"found {len(candidates)}"
        )
    return candidates[0]


def _training_summary_path(paths: ControlledPaths, spec: ExperimentSpec) -> Path:
    label = f"{spec.experiment_id}-seed{spec.seed}"
    return paths.training_root / "run_telemetry" / label / "run_summary.json"


def _run_training(
    *, paths: ControlledPaths, spec: ExperimentSpec, gpu: int
) -> dict[str, Any]:
    if spec.reference_adapter_path is not None:
        raise ValueError("reference experiments cannot be retrained by controlled-v2")
    [generated] = generate_configs([spec], paths=paths)
    summary_path = _training_summary_path(paths, spec)
    if summary_path.is_file():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if summary.get("training_succeeded") is True:
            return summary
        raise RuntimeError(
            f"previous training attempt is finalized as failed: {summary_path}"
        )
    env = os.environ.copy()
    env.update(
        {
            "STUDYHUB_SFT_GPU": str(gpu),
            "STUDYHUB_SFT_TELEMETRY_ROOT": str(paths.training_root / "run_telemetry"),
        }
    )
    command = [
        str(paths.project_root / "scripts/research/run-sft-with-telemetry.sh"),
        generated["config_path"],
        f"{spec.experiment_id}-seed{spec.seed}",
    ]
    completed = subprocess.run(command, cwd=paths.project_root, env=env, check=False)
    if completed.returncode != 0:
        raise RuntimeError(
            f"training failed for {spec.experiment_id}/seed={spec.seed}: "
            f"exit {completed.returncode}"
        )
    if not summary_path.is_file():
        raise RuntimeError(
            f"training completed without telemetry summary: {summary_path}"
        )
    return json.loads(summary_path.read_text(encoding="utf-8"))


def _annotate_summary(
    path: Path, spec: ExperimentSpec, *, config_sha256: str
) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    value.update(
        {
            "experiment_id": spec.experiment_id,
            "seed": spec.seed,
            "experiment_spec": spec.to_dict(),
            "config_sha256": config_sha256,
        }
    )
    _write_json(path, value)
    return value


def _run_evaluation(
    *, paths: ControlledPaths, spec: ExperimentSpec, gpu: int
) -> dict[str, Any]:
    evaluation_dir = paths.evaluation_root / spec.experiment_id / str(spec.seed)
    gate_path = evaluation_dir / "gate.json"
    if gate_path.is_file():
        return json.loads(gate_path.read_text(encoding="utf-8"))

    os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu)
    adapter = (
        Path(spec.reference_adapter_path)
        if spec.reference_adapter_path is not None
        else output_dir(paths, spec)
    )
    if not (adapter / "adapter_config.json").is_file():
        raise FileNotFoundError(f"trained adapter is incomplete: {adapter}")
    config_file = (
        Path(spec.reference_config_path)
        if spec.reference_config_path is not None
        else config_path(paths, spec)
    )
    config_hash = sha256_file(config_file)
    if spec.task == "router":
        evaluate_router_conditions(
            model_path=Path("/data/chengjin/studyhub/models/P0/Qwen3.5-2B"),
            adapter_path=adapter,
            dataset_path=paths.router_challenge,
            few_shot_path=paths.router_few_shot,
            output_root=evaluation_dir,
            conditions=("sft",),
        )
        raw_path = evaluation_dir / "sft/raw/summary.json"
        normalized_path = evaluation_dir / "sft/normalized/summary.json"
        projection_path = evaluation_dir / "sft/projection_comparison.json"
        raw = _annotate_summary(raw_path, spec, config_sha256=config_hash)
        _annotate_summary(normalized_path, spec, config_sha256=config_hash)
        projection = json.loads(projection_path.read_text(encoding="utf-8"))
        gate = gate_router(raw, projection)
    else:
        evaluate_tutor_conditions(
            model_path=Path("/data/chengjin/studyhub/models/P1/Qwen3.5-9B"),
            adapter_path=adapter,
            dataset_path=paths.tutor_challenge,
            few_shot_path=paths.tutor_few_shot,
            output_root=evaluation_dir,
            conditions=("sft",),
        )
        summary_path = evaluation_dir / "sft/raw/summary.json"
        summary = _annotate_summary(summary_path, spec, config_sha256=config_hash)
        gate = gate_tutor(summary)
    gate.update(
        {
            "experiment_id": spec.experiment_id,
            "seed": spec.seed,
            "config_sha256": config_hash,
        }
    )
    _write_json(gate_path, gate)
    return gate


def run_experiment(
    *,
    paths: ControlledPaths,
    spec: ExperimentSpec,
    gpu: int,
    train: bool = True,
    evaluate: bool = True,
) -> dict[str, Any]:
    training = _run_training(paths=paths, spec=spec, gpu=gpu) if train else None
    gate = _run_evaluation(paths=paths, spec=spec, gpu=gpu) if evaluate else None
    result = {
        "schema_version": "studyhub.agent.sft.controlled_v2.run_manifest.v1",
        "spec": spec.to_dict(),
        "training": training,
        "gate": gate,
    }
    _write_json(
        paths.evaluation_root
        / spec.experiment_id
        / str(spec.seed)
        / "run_manifest.json",
        result,
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--gpu", type=int, required=True, choices=(0, 1))
    parser.add_argument("--evaluate-only", action="store_true")
    parser.add_argument("--train-only", action="store_true")
    args = parser.parse_args()
    if args.evaluate_only and args.train_only:
        parser.error("--evaluate-only and --train-only are mutually exclusive")
    paths = ControlledPaths()
    spec = resolve_spec(paths=paths, experiment_id=args.experiment_id, seed=args.seed)
    result = run_experiment(
        paths=paths,
        spec=spec,
        gpu=args.gpu,
        train=not args.evaluate_only,
        evaluate=not args.train_only,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
