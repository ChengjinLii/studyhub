"""Aggregate five formal seeds, validate robustness, and freeze one candidate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..spec import sha256_file
from .gate import (
    assess_formal_training_run,
    assess_multi_seed,
    assess_validation_candidate,
    freeze_candidate,
    paired_bootstrap,
    screen_rank_key,
)
from .train_grpo import GRPOConfig


def gate_and_select(
    *,
    seeds: list[int],
    baseline_dir: Path,
    training_root: Path,
    evaluation_root: Path,
    config_path: Path,
    acceptance_path: Path,
    output_root: Path,
) -> dict[str, Any]:
    if len(seeds) != 5 or len(set(seeds)) != 5:
        raise ValueError("formal Gate requires exactly five distinct seeds")
    if output_root.exists() and any(output_root.iterdir()):
        raise FileExistsError(f"refusing to overwrite formal Gate: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    formal_config = GRPOConfig.load(config_path)
    if (
        formal_config.formal_run is not True
        or formal_config.raw.get("formal_protocol", {}).get("seeds") != seeds
    ):
        raise ValueError("formal config does not match the preregistered seed protocol")
    config_sha256 = sha256_file(config_path)
    acceptance_sha256 = sha256_file(acceptance_path)
    baseline_summary_path = baseline_dir / "summary.json"
    baseline_predictions_path = baseline_dir / "predictions.jsonl"
    baseline = _read_json(baseline_summary_path)
    rows: list[dict[str, Any]] = []
    assessments: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for seed in seeds:
        run_dir = training_root / f"seed_{seed}"
        training_summary_path = run_dir / "run_summary.json"
        metrics_path = run_dir / "trainer_metrics.jsonl"
        run_manifest_path = run_dir / "run_manifest.json"
        config_snapshot_path = run_dir / "config.snapshot.json"
        training = _read_json(training_summary_path)
        training_gate = assess_formal_training_run(
            summary=training,
            metrics_path=metrics_path,
            expected_seed=seed,
        )
        run_lock = _assess_run_lock(
            run_manifest_path=run_manifest_path,
            config_snapshot_path=config_snapshot_path,
            training_summary_path=training_summary_path,
            metrics_path=metrics_path,
            config_path=config_path,
            formal_config=formal_config.raw,
        )
        candidate_dir = evaluation_root / f"seed_{seed}"
        candidate_summary_path = candidate_dir / "summary.json"
        candidate_predictions_path = candidate_dir / "predictions.jsonl"
        candidate = _read_json(candidate_summary_path)
        statistics_result = paired_bootstrap(
            baseline_predictions_path,
            candidate_predictions_path,
        )
        validation = assess_validation_candidate(
            baseline=baseline,
            candidate=candidate,
            statistics_result=statistics_result,
        )
        combined_pass = (
            training_gate["passed"] and run_lock["passed"] and validation["passed"]
        )
        row = {
            "seed": seed,
            "passed": combined_pass,
            "training_gate": training_gate,
            "run_lock": run_lock,
            "validation_gate": validation,
            "rank_key": list(screen_rank_key(candidate, baseline)),
            "training_summary_path": str(training_summary_path.resolve()),
            "training_summary_sha256": sha256_file(training_summary_path),
            "run_manifest_path": str(run_manifest_path.resolve()),
            "run_manifest_sha256": sha256_file(run_manifest_path),
            "validation_summary_path": str(candidate_summary_path.resolve()),
            "validation_summary_sha256": sha256_file(candidate_summary_path),
        }
        rows.append(row)
        assessments.append(
            validation
            if training_gate["passed"] and run_lock["passed"]
            else {"passed": False}
        )
        summaries.append(candidate)
    multi_seed = assess_multi_seed(assessments, summaries)
    passing = [row for row in rows if row["passed"]]
    selected = max(passing, key=lambda row: tuple(row["rank_key"])) if passing else None
    overall_pass = multi_seed["passed"] and len(passing) == 5
    gate = {
        "schema_version": "studyhub.agent.router_rl.formal_validation_gate.v2",
        "passed": overall_pass,
        "status": (
            "validation_selected_pending_robustness"
            if overall_pass
            else "validation_gate_failed"
        ),
        "blockers": [
            *([] if len(passing) == 5 else ["all_five_training_and_validation_gates"]),
            *multi_seed["blockers"],
        ],
        "seeds": rows,
        "multi_seed": multi_seed,
        "selected_seed": selected["seed"] if selected and overall_pass else None,
        "selection_split": "validation",
        "formal_config_path": str(config_path.resolve()),
        "formal_config_sha256": config_sha256,
        "acceptance_path": str(acceptance_path.resolve()),
        "acceptance_sha256": acceptance_sha256,
        "test_read": False,
        "sealed_read": False,
        "production_access": False,
    }
    gate_path = output_root / "formal_validation_gate.json"
    _write_json(gate_path, gate)
    return gate


def _assess_run_lock(
    *,
    run_manifest_path: Path,
    config_snapshot_path: Path,
    training_summary_path: Path,
    metrics_path: Path,
    config_path: Path,
    formal_config: dict[str, Any],
) -> dict[str, Any]:
    """Cross-check one run against the frozen config and implementation."""

    manifest = _read_json(run_manifest_path)
    implementation_path = Path(__file__).with_name("train_grpo.py")
    train_path = Path(str(formal_config["train_path"]))
    reference_path = Path(str(formal_config["reference_cache_path"]))
    training_summary = _read_json(training_summary_path)
    schedule_path = Path(
        str(
            (training_summary.get("artifacts") or {}).get("episode_schedule_path") or ""
        )
    )
    expected_config_sha256 = sha256_file(config_path)
    checks = {
        "manifest_schema": manifest.get("schema_version")
        == "studyhub.agent.router_rl.training_manifest.v2",
        "config_snapshot_matches_frozen": sha256_file(config_snapshot_path)
        == expected_config_sha256,
        "manifest_config_matches_frozen": manifest.get("config_sha256")
        == expected_config_sha256,
        "summary_hash": manifest.get("summary_sha256")
        == sha256_file(training_summary_path),
        "metrics_hash": sha256_file(metrics_path)
        == training_summary.get("artifacts", {}).get("metrics_sha256"),
        "schedule_hash": schedule_path.is_file()
        and manifest.get("episode_schedule_sha256") == sha256_file(schedule_path)
        and training_summary.get("artifacts", {}).get("episode_schedule_sha256")
        == sha256_file(schedule_path),
        "train_hash": manifest.get("train_sha256") == sha256_file(train_path),
        "reference_hash": manifest.get("reference_cache_sha256")
        == sha256_file(reference_path),
        "implementation_hash": manifest.get("implementation_sha256")
        == sha256_file(implementation_path),
        "production_access": manifest.get("production_access") is False,
        "test_read": manifest.get("test_read") is False,
        "sealed_read": manifest.get("sealed_read") is False,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "blockers": sorted(name for name, passed in checks.items() if not passed),
        "config_sha256": expected_config_sha256,
        "implementation_sha256": sha256_file(implementation_path),
    }


def freeze_selected_candidate(
    *,
    gate_path: Path,
    baseline_dir: Path,
    training_root: Path,
    evaluation_root: Path,
    robustness_summary_path: Path,
    config_path: Path,
    acceptance_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    gate = _read_json(gate_path)
    if gate.get("passed") is not True:
        raise ValueError("cannot freeze a failed formal Validation Gate")
    if gate.get("status") != "validation_selected_pending_robustness":
        raise ValueError("formal Gate is not waiting for robustness")
    if gate.get("formal_config_sha256") != sha256_file(config_path):
        raise ValueError("formal config changed after Validation selection")
    if gate.get("acceptance_sha256") != sha256_file(acceptance_path):
        raise ValueError("acceptance criteria changed after Validation selection")
    selected_seed = int(gate["selected_seed"])
    selected = next(row for row in gate["seeds"] if int(row["seed"]) == selected_seed)
    robustness = _read_json(robustness_summary_path)
    if robustness.get("passed") is not True:
        raise ValueError("cannot freeze a candidate that failed robustness")
    if robustness.get("split") != "validation" or any(
        value is not False for value in (robustness.get("isolation") or {}).values()
    ):
        raise ValueError("robustness evidence is not isolated Validation evidence")
    candidate_summary_path = evaluation_root / f"seed_{selected_seed}" / "summary.json"
    candidate = _read_json(candidate_summary_path)
    if selected.get("validation_summary_sha256") != sha256_file(candidate_summary_path):
        raise ValueError("selected Validation summary changed before freeze")
    if robustness.get("adapter_sha256") != candidate.get("adapter_sha256"):
        raise ValueError("robustness evaluation used a different adapter")
    training_summary_path = training_root / f"seed_{selected_seed}" / "run_summary.json"
    if selected.get("training_summary_sha256") != sha256_file(training_summary_path):
        raise ValueError("selected training summary changed before freeze")
    run_manifest_path = training_root / f"seed_{selected_seed}" / "run_manifest.json"
    if selected.get("run_manifest_sha256") != sha256_file(run_manifest_path):
        raise ValueError("selected run manifest changed before freeze")
    frozen = freeze_candidate(
        output_path=output_path,
        baseline_summary_path=baseline_dir / "summary.json",
        candidate_summary_path=candidate_summary_path,
        training_summary_path=training_summary_path,
        config_path=config_path,
        acceptance_path=acceptance_path,
        assessment=selected["validation_gate"],
        multi_seed=gate["multi_seed"],
    )
    gate.update(
        {
            "status": "frozen_after_validation_and_robustness",
            "robustness_summary_path": str(robustness_summary_path.resolve()),
            "robustness_summary_sha256": sha256_file(robustness_summary_path),
            "frozen_candidate_path": str(output_path.resolve()),
            "frozen_candidate_sha256": sha256_file(output_path),
            "frozen_candidate": frozen,
        }
    )
    _write_json(gate_path, gate)
    return gate


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    select = subparsers.add_parser("select")
    select.add_argument("--seeds", type=int, nargs=5, required=True)
    select.add_argument("--baseline-dir", type=Path, required=True)
    select.add_argument("--training-root", type=Path, required=True)
    select.add_argument("--evaluation-root", type=Path, required=True)
    select.add_argument("--config", type=Path, required=True)
    select.add_argument("--acceptance", type=Path, required=True)
    select.add_argument("--output-root", type=Path, required=True)
    freeze = subparsers.add_parser("freeze")
    freeze.add_argument("--gate", type=Path, required=True)
    freeze.add_argument("--baseline-dir", type=Path, required=True)
    freeze.add_argument("--training-root", type=Path, required=True)
    freeze.add_argument("--evaluation-root", type=Path, required=True)
    freeze.add_argument("--robustness-summary", type=Path, required=True)
    freeze.add_argument("--config", type=Path, required=True)
    freeze.add_argument("--acceptance", type=Path, required=True)
    freeze.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "select":
        result = gate_and_select(
            seeds=args.seeds,
            baseline_dir=args.baseline_dir.resolve(),
            training_root=args.training_root.resolve(),
            evaluation_root=args.evaluation_root.resolve(),
            config_path=args.config.resolve(),
            acceptance_path=args.acceptance.resolve(),
            output_root=args.output_root.resolve(),
        )
    else:
        result = freeze_selected_candidate(
            gate_path=args.gate.resolve(),
            baseline_dir=args.baseline_dir.resolve(),
            training_root=args.training_root.resolve(),
            evaluation_root=args.evaluation_root.resolve(),
            robustness_summary_path=args.robustness_summary.resolve(),
            config_path=args.config.resolve(),
            acceptance_path=args.acceptance.resolve(),
            output_path=args.output.resolve(),
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if not result["passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
