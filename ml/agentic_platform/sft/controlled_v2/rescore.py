"""Rescore saved generations after a documented scorer-only contract correction."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from ..spec import load_jsonl, sha256_file
from .contract import ControlledPaths
from .evaluate import _router_scores, _router_summary, _tutor_scores, _tutor_summary
from .gates import gate_router, gate_tutor

CORRECTION_ID = "router-deterministic-arguments-only-v1"
TUTOR_CORRECTION_ID = "tutor-independent-no-tool-and-scope-v1"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def rescore_router_run(
    *,
    experiment_id: str,
    seed: int,
    paths: ControlledPaths | None = None,
) -> dict[str, Any]:
    paths = paths or ControlledPaths()
    run_dir = paths.evaluation_root / experiment_id / str(seed)
    source = {row["example_id"]: row for row in load_jsonl(paths.router_challenge)}
    summaries: dict[str, dict[str, Any]] = {}
    rescored_rows: dict[str, list[dict[str, Any]]] = {}
    for projection, directory in (("raw", "raw"), ("runtime_projected", "normalized")):
        prediction_path = run_dir / "sft" / directory / "predictions.jsonl"
        summary_path = run_dir / "sft" / directory / "summary.json"
        backup_predictions = prediction_path.with_name(
            "predictions.pre_contract_alignment.jsonl"
        )
        backup_summary = summary_path.with_name("summary.pre_contract_alignment.json")
        if not backup_predictions.exists():
            shutil.copy2(prediction_path, backup_predictions)
        if not backup_summary.exists():
            shutil.copy2(summary_path, backup_summary)
        old_summary = json.loads(summary_path.read_text(encoding="utf-8"))
        rows = load_jsonl(prediction_path)
        for row in rows:
            record = source[str(row["example_id"])]
            row["scores"] = _router_scores(record, row.get("parsed"))
            row["scorer_correction_id"] = CORRECTION_ID
        summary = _router_summary(
            rows,
            model_path=Path(old_summary["model_path"]),
            adapter_path=(
                Path(old_summary["adapter_path"])
                if old_summary.get("adapter_path")
                else None
            ),
            condition="sft",
            projection=projection,
            runtime=old_summary["runtime"],
        )
        for key in ("experiment_id", "seed", "experiment_spec", "config_sha256"):
            if key in old_summary:
                summary[key] = old_summary[key]
        summary["input_contract"] = old_summary.get("input_contract") or {
            "dataset_path": str(paths.router_challenge),
            "dataset_sha256": sha256_file(paths.router_challenge),
            "few_shot_path": str(paths.router_few_shot),
            "few_shot_sha256": sha256_file(paths.router_few_shot),
        }
        summary["scorer_correction_id"] = CORRECTION_ID
        _write_jsonl(prediction_path, rows)
        _write_json(summary_path, summary)
        rescored_rows[projection] = rows
        summaries[projection] = summary

    raw_rows = rescored_rows["raw"]
    projected_rows = rescored_rows["runtime_projected"]
    corrections = sum(
        not bool(raw["scores"]["strict_route_pass"])
        and bool(projected["scores"]["strict_route_pass"])
        for raw, projected in zip(raw_rows, projected_rows, strict=True)
    )
    regressions = sum(
        bool(raw["scores"]["strict_route_pass"])
        and not bool(projected["scores"]["strict_route_pass"])
        for raw, projected in zip(raw_rows, projected_rows, strict=True)
    )
    modified = sum(
        bool((row.get("constraint") or {}).get("corrections")) for row in projected_rows
    )
    comparison = {
        "records": len(raw_rows),
        "raw_strict_rate": summaries["raw"]["metrics"]["strict_route_pass"]["rate"],
        "projected_strict_rate": summaries["runtime_projected"]["metrics"][
            "strict_route_pass"
        ]["rate"],
        "projection_rescues": corrections,
        "projection_regressions": regressions,
        "projection_modified_records": modified,
        "projection_correction_rate": round(corrections / len(raw_rows), 6),
        "projection_guardrail_activation_rate": round(modified / len(raw_rows), 6),
        "scorer_correction_id": CORRECTION_ID,
    }
    comparison_path = run_dir / "sft/projection_comparison.json"
    backup_comparison = comparison_path.with_name(
        "projection_comparison.pre_contract_alignment.json"
    )
    if not backup_comparison.exists():
        shutil.copy2(comparison_path, backup_comparison)
    _write_json(comparison_path, comparison)
    gate_path = run_dir / "gate.json"
    backup_gate = gate_path.with_name("gate.pre_contract_alignment.json")
    if gate_path.exists() and not backup_gate.exists():
        shutil.copy2(gate_path, backup_gate)
    gate = gate_router(summaries["raw"], comparison)
    gate.update(
        {
            "experiment_id": experiment_id,
            "seed": seed,
            "config_sha256": summaries["raw"].get("config_sha256"),
            "scorer_correction_id": CORRECTION_ID,
        }
    )
    _write_json(gate_path, gate)
    correction = {
        "schema_version": "studyhub.agent.sft.controlled_v2.scorer_correction.v1",
        "correction_id": CORRECTION_ID,
        "scope": "saved predictions only; no regeneration, data, model, or threshold change",
        "reason": (
            "The roadmap pre-registered exact material IDs and page numbers. The "
            "initial implementation incorrectly included free-text query, progress, "
            "and synthesis wording in the strict route decision, and conflated "
            "general contract correctness with the separately registered injection "
            "and permission safety checks for scoring and screening eligibility."
        ),
        "preserved_originals": {
            "raw_predictions": str(
                run_dir / "sft/raw/predictions.pre_contract_alignment.jsonl"
            ),
            "normalized_predictions": str(
                run_dir / "sft/normalized/predictions.pre_contract_alignment.jsonl"
            ),
            "gate": str(backup_gate),
        },
        "input_generation_sha256": {
            "raw": sha256_file(
                run_dir / "sft/raw/predictions.pre_contract_alignment.jsonl"
            ),
            "normalized": sha256_file(
                run_dir / "sft/normalized/predictions.pre_contract_alignment.jsonl"
            ),
        },
        "result_gate": gate,
    }
    _write_json(run_dir / "scorer_correction.json", correction)
    index_path = paths.contract_dir / "scorer_corrections.json"
    index = (
        json.loads(index_path.read_text(encoding="utf-8"))
        if index_path.is_file()
        else {
            "schema_version": "studyhub.agent.sft.controlled_v2.scorer_corrections.v1",
            "corrections": [],
        }
    )
    matching = [
        item
        for item in index["corrections"]
        if item.get("correction_id") == CORRECTION_ID
    ]
    if matching:
        matching[0]["reason"] = correction["reason"]
        matching[0]["scope"] = correction["scope"]
    else:
        index["corrections"].append(
            {
                "correction_id": CORRECTION_ID,
                "reason": correction["reason"],
                "scope": correction["scope"],
                "first_observed_run": f"{experiment_id}/{seed}",
                "thresholds_changed": False,
                "data_changed": False,
                "generations_changed": False,
            }
        )
    _write_json(index_path, index)
    prereg = json.loads(paths.pre_registration.read_text(encoding="utf-8"))
    prereg["audit"]["scorer_corrections_path"] = str(index_path)
    prereg["audit"]["scorer_corrections_sha256"] = sha256_file(index_path)
    _write_json(paths.pre_registration, prereg)
    return correction


def rescore_tutor_run(
    *,
    experiment_id: str,
    seed: int,
    paths: ControlledPaths | None = None,
) -> dict[str, Any]:
    paths = paths or ControlledPaths()
    run_dir = paths.evaluation_root / experiment_id / str(seed)
    source = {row["example_id"]: row for row in load_jsonl(paths.tutor_challenge)}
    prediction_path = run_dir / "sft/raw/predictions.jsonl"
    summary_path = run_dir / "sft/raw/summary.json"
    backup_predictions = prediction_path.with_name(
        "predictions.pre_scorer_alignment.jsonl"
    )
    backup_summary = summary_path.with_name("summary.pre_scorer_alignment.json")
    if not backup_predictions.exists():
        shutil.copy2(prediction_path, backup_predictions)
    if not backup_summary.exists():
        shutil.copy2(summary_path, backup_summary)

    old_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    rows = load_jsonl(prediction_path)
    for row in rows:
        record = source[str(row["example_id"])]
        row["scores"] = _tutor_scores(
            record,
            row.get("parsed"),
            str(row.get("generated") or ""),
        )
        row["scorer_correction_id"] = TUTOR_CORRECTION_ID
    summary = _tutor_summary(
        rows,
        model_path=Path(old_summary["model_path"]),
        adapter_path=(
            Path(old_summary["adapter_path"])
            if old_summary.get("adapter_path")
            else None
        ),
        condition="sft",
        runtime=old_summary["runtime"],
    )
    for key in ("experiment_id", "seed", "experiment_spec", "config_sha256"):
        if key in old_summary:
            summary[key] = old_summary[key]
    summary["input_contract"] = old_summary.get("input_contract") or {
        "dataset_path": str(paths.tutor_challenge),
        "dataset_sha256": sha256_file(paths.tutor_challenge),
        "few_shot_path": str(paths.tutor_few_shot),
        "few_shot_sha256": sha256_file(paths.tutor_few_shot),
    }
    summary["scorer_correction_id"] = TUTOR_CORRECTION_ID
    _write_jsonl(prediction_path, rows)
    _write_json(summary_path, summary)

    gate_path = run_dir / "gate.json"
    backup_gate = gate_path.with_name("gate.pre_scorer_alignment.json")
    if gate_path.exists() and not backup_gate.exists():
        shutil.copy2(gate_path, backup_gate)
    gate = gate_tutor(summary)
    gate.update(
        {
            "experiment_id": experiment_id,
            "seed": seed,
            "config_sha256": summary.get("config_sha256"),
            "scorer_correction_id": TUTOR_CORRECTION_ID,
        }
    )
    _write_json(gate_path, gate)

    correction = {
        "schema_version": "studyhub.agent.sft.controlled_v2.scorer_correction.v1",
        "correction_id": TUTOR_CORRECTION_ID,
        "scope": "saved predictions only; no regeneration, data, model, or threshold change",
        "reason": (
            "The pre-registered no-tool safety metric is independent of JSON and "
            "contract validity. The initial scorer marked every unparsable output "
            "as a tool-action failure even when the generated text contained no "
            "actions field. Partial-evidence disclosure also omitted equivalent "
            "scope phrases such as '只覆盖' and '不代表整份'."
        ),
        "preserved_originals": {
            "predictions": str(backup_predictions),
            "summary": str(backup_summary),
            "gate": str(backup_gate),
        },
        "input_generation_sha256": sha256_file(backup_predictions),
        "result_gate": gate,
    }
    _write_json(run_dir / "scorer_correction.json", correction)

    index_path = paths.contract_dir / "scorer_corrections.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    matching = [
        item
        for item in index["corrections"]
        if item.get("correction_id") == TUTOR_CORRECTION_ID
    ]
    if matching:
        matching[0]["reason"] = correction["reason"]
        matching[0]["scope"] = correction["scope"]
    else:
        index["corrections"].append(
            {
                "correction_id": TUTOR_CORRECTION_ID,
                "reason": correction["reason"],
                "scope": correction["scope"],
                "first_observed_run": f"{experiment_id}/{seed}",
                "thresholds_changed": False,
                "data_changed": False,
                "generations_changed": False,
            }
        )
    _write_json(index_path, index)
    prereg = json.loads(paths.pre_registration.read_text(encoding="utf-8"))
    prereg["audit"]["scorer_corrections_path"] = str(index_path)
    prereg["audit"]["scorer_corrections_sha256"] = sha256_file(index_path)
    _write_json(paths.pre_registration, prereg)
    return correction


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", choices=("router", "tutor"), default="router")
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args()
    function = rescore_router_run if args.task == "router" else rescore_tutor_run
    result = function(experiment_id=args.experiment_id, seed=args.seed)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
