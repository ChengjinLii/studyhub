"""Build a machine-readable index of every controlled-v2 experiment artifact."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from dataclasses import fields
from pathlib import Path
from typing import Any

from ..spec import sha256_file
from .configs import config_path, output_dir
from .contract import ControlledPaths, ExperimentSpec

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


def _optional_json(path: Path) -> dict[str, Any] | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _artifact(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "exists": path.is_file(),
        "sha256": sha256_file(path) if path.is_file() else None,
    }


def _telemetry_path(paths: ControlledPaths, spec: ExperimentSpec) -> Path:
    if spec.reference_adapter_path:
        try:
            telemetry_id = REFERENCE_TELEMETRY[spec.experiment_id]
        except KeyError as exc:
            raise ValueError(
                f"reference telemetry is not registered: {spec.experiment_id}"
            ) from exc
        return (
            paths.project_root
            / "training_artifacts/studyhub_agent_sft/run_telemetry"
            / telemetry_id
            / "run_summary.json"
        )
    return (
        paths.training_root
        / "run_telemetry"
        / f"{spec.experiment_id}-seed{spec.seed}"
        / "run_summary.json"
    )


def _experiment_row(paths: ControlledPaths, spec: ExperimentSpec) -> dict[str, Any]:
    evaluation_dir = paths.evaluation_root / spec.experiment_id / str(spec.seed)
    gate_path = evaluation_dir / "gate.json"
    telemetry_path = _telemetry_path(paths, spec)
    if spec.reference_adapter_path:
        adapter = Path(spec.reference_adapter_path)
        config = Path(str(spec.reference_config_path))
        training_kind = "completed_reference"
    else:
        adapter = output_dir(paths, spec)
        config = config_path(paths, spec)
        training_kind = "controlled_v2"
    gate = _optional_json(gate_path)
    telemetry = _optional_json(telemetry_path)
    return {
        "spec": spec.to_dict(),
        "training_kind": training_kind,
        "config": _artifact(config),
        "adapter": _artifact(adapter / "adapter_model.safetensors"),
        "telemetry": _artifact(telemetry_path),
        "training_succeeded": (
            bool(telemetry.get("training_succeeded")) if telemetry else None
        ),
        "evaluation": {
            "gate": _artifact(gate_path),
            "raw_summary": _artifact(evaluation_dir / "sft/raw/summary.json"),
            "raw_predictions": _artifact(evaluation_dir / "sft/raw/predictions.jsonl"),
        },
        "gate_passed": bool(gate.get("passed")) if gate else None,
        "screening_eligible": (bool(gate.get("screening_eligible")) if gate else None),
        "selection_score": gate.get("selection_score") if gate else None,
        "gate_failures": gate.get("failures", {}) if gate else {},
    }


def build_result_index(*, paths: ControlledPaths | None = None) -> dict[str, Any]:
    paths = paths or ControlledPaths()
    registry = json.loads(paths.experiment_registry.read_text(encoding="utf-8"))
    sections = (
        "initial_experiments",
        "reference_experiments",
        "dynamic_experiments",
    )
    specs = [_spec(item) for section in sections for item in registry.get(section, [])]
    rows = [_experiment_row(paths, spec) for spec in specs]
    counts = {
        "registered": len(rows),
        "controlled_training_completed": sum(
            item["training_kind"] == "controlled_v2"
            and item["training_succeeded"] is True
            for item in rows
        ),
        "evaluated": sum(item["gate_passed"] is not None for item in rows),
        "gate_passed": sum(item["gate_passed"] is True for item in rows),
        "screening_eligible": sum(item["screening_eligible"] is True for item in rows),
    }
    baseline_root = paths.evaluation_root / "baselines"
    final_root = paths.evaluation_root / "final"
    result = {
        "schema_version": "studyhub.agent.sft.controlled_v2.result_index.v1",
        "contract": {
            "pre_registration": _artifact(paths.pre_registration),
            "audit": _artifact(paths.contract_dir / "audit.json"),
            "registry": _artifact(paths.experiment_registry),
        },
        "registry_status": registry.get("status"),
        "counts": counts,
        "experiments": rows,
        "baselines": {
            task: _artifact(baseline_root / task / "baseline_index.json")
            for task in ("router", "tutor")
        },
        "ablations": {
            task: _artifact(
                paths.evaluation_root
                / "ablation"
                / task
                / "ablation_index.json"
            )
            for task in ("router", "tutor")
        },
        "context_study": _artifact(
            paths.evaluation_root / "t-context/results/context_study_index.json"
        ),
        "final": {
            task: {
                "decision": _artifact(final_root / task / "final_decision.json"),
                "sealed_receipt": _artifact(
                    final_root / task / "sealed_evaluation_receipt.json"
                ),
            }
            for task in ("router", "tutor")
        },
        "completion_audit": _artifact(
            paths.evaluation_root / "final/completion_audit.json"
        ),
        "completion_report_manifest": _artifact(
            paths.evaluation_root / "final/completion_report_manifest.json"
        ),
    }
    _write_json(paths.evaluation_root / "result_index.json", result)
    return result


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    result = build_result_index()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
