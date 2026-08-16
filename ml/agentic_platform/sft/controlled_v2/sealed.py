"""Run the single-use sealed evaluation after controlled-v2 selection is frozen."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from ..spec import sha256_file
from .configs import ROUTER_MODEL, TUTOR_MODEL, config_path, output_dir
from .contract import ControlledPaths
from .evaluate import evaluate_router_conditions, evaluate_tutor_conditions
from .finalize import _winner_specs
from .gates import gate_router, gate_tutor

Task = Literal["router", "tutor"]


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_exclusive_json(path: Path, value: object) -> None:
    """Create an immutable claim; an interrupted attempt still consumes the seal."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise FileExistsError(f"sealed evaluation was already claimed: {path}") from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _git_state(project_root: Path) -> dict[str, Any]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=normal"],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    return {"commit": commit, "dirty": bool(status), "status": status}


def _sealed_inputs(paths: ControlledPaths, task: Task) -> tuple[Path, Path, Path]:
    if task == "router":
        root = (
            paths.project_root
            / "evaluation_artifacts/studyhub_agent/router_final_holdout_v2"
        )
        return root / "router_final_holdout_300.jsonl", root / "seal.json", root
    return (
        paths.tutor_sealed,
        paths.contract_dir / "tutor_sealed_test_v2_seal.json",
        paths.contract_dir,
    )


def run_sealed_evaluation(
    *,
    task: Task,
    gpu: int,
    paths: ControlledPaths | None = None,
) -> dict[str, Any]:
    paths = paths or ControlledPaths()
    decision_path = paths.evaluation_root / "final" / task / "final_decision.json"
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    if not decision.get("passed"):
        raise RuntimeError(
            "sealed evaluation is blocked because the development Gate failed"
        )
    if decision.get("sealed_data_read") is not False:
        raise RuntimeError("final decision does not certify an unread sealed dataset")

    receipt_path = (
        paths.evaluation_root / "final" / task / "sealed_evaluation_receipt.json"
    )
    if receipt_path.exists():
        raise FileExistsError(f"sealed evaluation already recorded: {receipt_path}")

    experiment_id = str(decision["experiment_id"])
    delivery_seed = int(decision["delivery_seed"])
    specs = _winner_specs(paths=paths, task=task, experiment_id=experiment_id)
    spec = next(item for item in specs if item.seed == delivery_seed)
    adapter = (
        Path(spec.reference_adapter_path)
        if spec.reference_adapter_path
        else output_dir(paths, spec)
    )
    config = (
        Path(spec.reference_config_path)
        if spec.reference_config_path
        else config_path(paths, spec)
    )
    weights = adapter / "adapter_model.safetensors"
    if not weights.is_file():
        raise FileNotFoundError(weights)

    dataset, seal_path, _ = _sealed_inputs(paths, task)
    if not dataset.is_file():
        raise FileNotFoundError(dataset)
    if not seal_path.is_file():
        raise FileNotFoundError(seal_path)

    output_root = paths.evaluation_root / "final" / task / "sealed"
    if output_root.exists() and any(output_root.iterdir()):
        raise FileExistsError(f"sealed output directory is not empty: {output_root}")

    claim_path = (
        paths.evaluation_root / "final" / task / "sealed_evaluation_claim.json"
    )
    claim = {
        "schema_version": "studyhub.agent.sft.controlled_v2.sealed_claim.v1",
        "task": task,
        "claimed_at": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat(),
        "pid": os.getpid(),
        "development_decision": {
            "path": str(decision_path),
            "sha256": sha256_file(decision_path),
            "experiment_id": experiment_id,
            "delivery_seed": delivery_seed,
        },
        "selected_adapter": {
            "path": str(adapter),
            "weight_sha256": sha256_file(weights),
            "config_path": str(config),
            "config_sha256": sha256_file(config),
        },
        "sealed_dataset_path": str(dataset),
        "policy": {
            "claim_is_single_use": True,
            "claim_removed_after_failure": False,
        },
    }
    _write_exclusive_json(claim_path, claim)

    # From this point onward the immutable claim records that the sealed data was read.
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    dataset_sha = sha256_file(dataset)
    if dataset_sha != seal["dataset_sha256"]:
        raise ValueError("sealed dataset hash does not match its immutable seal")
    if bool(seal.get("evaluated")):
        raise RuntimeError("the immutable seal reports that this dataset was evaluated")

    os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu)
    if task == "router":
        evaluation = evaluate_router_conditions(
            model_path=ROUTER_MODEL,
            adapter_path=adapter,
            dataset_path=dataset,
            few_shot_path=paths.router_few_shot,
            output_root=output_root,
            conditions=("sft",),
        )
        summary = evaluation["sft"]["raw"]
        gate = gate_router(summary, evaluation["sft"]["projection_comparison"])
    else:
        evaluation = evaluate_tutor_conditions(
            model_path=TUTOR_MODEL,
            adapter_path=adapter,
            dataset_path=dataset,
            few_shot_path=paths.tutor_few_shot,
            output_root=output_root,
            conditions=("sft",),
        )
        summary = evaluation["sft"]
        gate = gate_tutor(summary)
    _write_json(output_root / "gate.json", gate)

    predictions_path = output_root / "sft/raw/predictions.jsonl"
    summary_path = output_root / "sft/raw/summary.json"
    receipt = {
        "schema_version": "studyhub.agent.sft.controlled_v2.sealed_receipt.v2",
        "evaluation_count": 1,
        "evaluated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "task": task,
        "selected_before_sealed_evaluation": True,
        "single_use_claim": {
            "path": str(claim_path),
            "sha256": sha256_file(claim_path),
        },
        "development_decision": {
            "path": str(decision_path),
            "sha256": sha256_file(decision_path),
            "experiment_id": experiment_id,
            "delivery_seed": delivery_seed,
        },
        "selected_adapter": {
            "path": str(adapter),
            "weight_sha256": sha256_file(weights),
            "config_path": str(config),
            "config_sha256": sha256_file(config),
        },
        "sealed_dataset": {
            "path": str(dataset),
            "sha256": dataset_sha,
            "seal_path": str(seal_path),
            "seal_sha256": sha256_file(seal_path),
            "records": int(seal["records"]),
        },
        "outputs": {
            "predictions_path": str(predictions_path),
            "predictions_sha256": sha256_file(predictions_path),
            "summary_path": str(summary_path),
            "summary_sha256": sha256_file(summary_path),
            "gate_path": str(output_root / "gate.json"),
            "gate_sha256": sha256_file(output_root / "gate.json"),
        },
        "sealed_gate": gate,
        "git": _git_state(paths.project_root),
        "policy": {
            "repeat_evaluation_allowed": False,
            "sealed_result_used_for_model_selection": False,
        },
    }
    _write_json(receipt_path, receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", choices=("router", "tutor"))
    parser.add_argument("--gpu", type=int, required=True, choices=(0, 1))
    args = parser.parse_args()
    result = run_sealed_evaluation(task=args.task, gpu=args.gpu)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
