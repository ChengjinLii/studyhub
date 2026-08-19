"""Audit controlled-v2 completion against the frozen SFT Roadmap."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import fields
from pathlib import Path
from typing import Any

from ..spec import load_jsonl, sha256_file
from .configs import output_dir
from .contract import ControlledPaths, ExperimentSpec, contract_sha256

EXPECTED_SELECTION_STAGES = {
    "router-lr",
    "router-epoch",
    "router-scheduler",
    "router-lora-rank",
    "router-lora-target",
    "tutor-lr",
    "tutor-lora",
}
EXPECTED_DYNAMIC_COUNTS = {
    "r-opt-epoch": {2, 4},
    "r-opt-scheduler": {1},
    "r-lora-rank": {2},
    "r-lora-target": {1},
    "r-seed": {2},
    "r-data-scale": {4},
    "r-data-replay": {4},
    "r-data-state": {3},
    "t-lora-rank": {2},
    "t-seed": {2},
    "t-mix": {3},
}
EXPECTED_ABLATION_STAGES = {
    "router": {
        "router-lr",
        "router-epoch",
        "router-scheduler",
        "router-lora-rank",
        "router-lora-target",
        "r-data-scale",
        "r-data-replay",
        "r-data-state",
    },
    "tutor": {"tutor-lr", "tutor-lora", "t-mix"},
}
EXPECTED_SEEDS = {
    "router": {3407, 7703, 9109},
    "tutor": {3407, 6209, 9109},
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


def _optional_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _spec(value: Mapping[str, Any]) -> ExperimentSpec:
    allowed = {field.name for field in fields(ExperimentSpec)}
    return ExperimentSpec(**{key: value[key] for key in allowed if key in value})


def _requirement(
    requirement_id: str,
    title: str,
    passed: bool,
    *,
    evidence: Sequence[Path] = (),
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": requirement_id,
        "title": title,
        "passed": bool(passed),
        "evidence": [
            {
                "path": str(path),
                "exists": path.is_file(),
                "sha256": sha256_file(path) if path.is_file() else None,
            }
            for path in evidence
        ],
        "details": dict(details or {}),
    }


def _telemetry_path(paths: ControlledPaths, spec: ExperimentSpec) -> Path:
    if spec.reference_adapter_path:
        return (
            paths.project_root
            / "training_artifacts/studyhub_agent_sft/run_telemetry"
            / REFERENCE_TELEMETRY[spec.experiment_id]
            / "run_summary.json"
        )
    return (
        paths.training_root
        / "run_telemetry"
        / f"{spec.experiment_id}-seed{spec.seed}"
        / "run_summary.json"
    )


def _experiment_evidence(
    paths: ControlledPaths, specs: Sequence[ExperimentSpec]
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for spec in specs:
        telemetry_path = _telemetry_path(paths, spec)
        telemetry = _optional_json(telemetry_path)
        gate_path = (
            paths.evaluation_root
            / spec.experiment_id
            / str(spec.seed)
            / "gate.json"
        )
        adapter = (
            Path(spec.reference_adapter_path)
            if spec.reference_adapter_path
            else output_dir(paths, spec)
        )
        weights = adapter / "adapter_model.safetensors"
        rows.append(
            {
                "experiment_id": spec.experiment_id,
                "task": spec.task,
                "stage": spec.stage,
                "seed": spec.seed,
                "reference": bool(spec.reference_adapter_path),
                "adapter_exists": weights.is_file(),
                "training_succeeded": (
                    True
                    if spec.reference_adapter_path
                    else bool(telemetry and telemetry.get("training_succeeded"))
                ),
                "telemetry_exists": telemetry_path.is_file(),
                "evaluated": gate_path.is_file(),
                "gate_passed": (
                    bool(_optional_json(gate_path).get("passed"))
                    if _optional_json(gate_path)
                    else None
                ),
            }
        )
    return {
        "rows": rows,
        "all_adapters_exist": all(item["adapter_exists"] for item in rows),
        "all_telemetry_exists": all(item["telemetry_exists"] for item in rows),
        "all_training_succeeded": all(item["training_succeeded"] for item in rows),
        "all_evaluated": all(item["evaluated"] for item in rows),
    }


def _baseline_requirement(paths: ControlledPaths, task: str) -> dict[str, Any]:
    path = paths.evaluation_root / "baselines" / task / "baseline_index.json"
    value = _optional_json(path)
    conditions = set(value.get("conditions", [])) if value else set()
    paired = set(value.get("paired_comparisons", {})) if value else set()
    expected_baselines = {"base", "prompt", "few_shot"}
    condition_artifacts = (value or {}).get("condition_artifacts", {})
    reference_artifacts = (value or {}).get("reference_artifacts", {})
    comparison_artifacts = (value or {}).get("paired_comparison_artifacts", {})

    def artifact_valid(artifact: Mapping[str, Any]) -> bool:
        artifact_path = artifact.get("path")
        if not isinstance(artifact_path, str) or not artifact_path:
            return False
        candidate = Path(artifact_path)
        if not candidate.is_file() or artifact.get("sha256") != sha256_file(candidate):
            return False
        records = artifact.get("records")
        if records is not None:
            try:
                observed = len(load_jsonl(candidate))
            except (OSError, ValueError):
                return False
            if observed != int(records):
                return False
        return True

    indexed_artifacts = [
        artifact
        for group in condition_artifacts.values()
        if isinstance(group, Mapping)
        for artifact in group.values()
        if isinstance(artifact, Mapping)
    ]
    indexed_artifacts.extend(
        artifact
        for artifact in reference_artifacts.values()
        if isinstance(artifact, Mapping)
    )
    indexed_artifacts.extend(
        artifact
        for artifact in comparison_artifacts.values()
        if isinstance(artifact, Mapping)
    )
    artifacts_valid = (
        set(condition_artifacts) == expected_baselines
        and set(comparison_artifacts) == expected_baselines
        and set(reference_artifacts) == {"predictions", "summary", "gate"}
        and bool(indexed_artifacts)
        and all(artifact_valid(item) for item in indexed_artifacts)
    )
    passed = all(
        (
            (value or {}).get("schema_version")
            == "studyhub.agent.sft.controlled_v2.baselines.v2",
            (value or {}).get("task") == task,
            conditions == {*expected_baselines, "sft"},
            paired == expected_baselines,
            artifacts_valid,
        )
    )
    evidence_paths = tuple(
        Path(item["path"])
        for item in indexed_artifacts
        if isinstance(item.get("path"), str)
    )
    return _requirement(
        f"{task}_baselines",
        f"{task.title()} Base / Prompt / Few-shot / SFT paired baselines",
        passed,
        evidence=(path, *evidence_paths),
        details={
            "conditions": sorted(conditions),
            "paired_comparisons": sorted(paired),
            "indexed_artifacts": len(indexed_artifacts),
            "artifacts_valid": artifacts_valid,
        },
    )


def _ablation_requirement(paths: ControlledPaths, task: str) -> dict[str, Any]:
    path = paths.evaluation_root / "ablation" / task / "ablation_index.json"
    value = _optional_json(path)
    stages = {str(item.get("stage")) for item in value.get("groups", [])} if value else set()
    resources_validated = bool(value) and all(
        "resource_comparison_valid" in item for item in value.get("groups", [])
    )
    paired_present = bool(value) and all(
        all(
            arm.get("is_anchor") or arm.get("paired_primary_vs_anchor")
            for arm in group.get("arms", [])
        )
        for group in value.get("groups", [])
    )
    passed = (
        stages == EXPECTED_ABLATION_STAGES[task]
        and resources_validated
        and paired_present
        and value.get("sealed_data_read") is False
    )
    return _requirement(
        f"{task}_ablations",
        f"{task.title()} optimization and attribution ablations",
        passed,
        evidence=(path,),
        details={
            "expected_stages": sorted(EXPECTED_ABLATION_STAGES[task]),
            "observed_stages": sorted(stages),
            "paired_statistics_present": paired_present,
            "resource_fields_present": resources_validated,
        },
    )


def _final_requirement(paths: ControlledPaths, task: str) -> dict[str, Any]:
    path = paths.evaluation_root / "final" / task / "final_decision.json"
    value = _optional_json(path)
    observed_seeds = {
        int(item["seed"])
        for item in (value or {}).get("seed_summary", {}).get("seeds", [])
    }
    comparisons = set((value or {}).get("paired_comparisons", {}))
    resources = (value or {}).get("resources", {}).get("per_seed", [])
    passed = bool(value) and all(
        (
            value.get("passed") is True,
            observed_seeds == EXPECTED_SEEDS[task],
            comparisons == {"base", "prompt", "few_shot", "completed_sft_reference"},
            len(resources) == 3,
            value.get("sealed_data_read") is False,
        )
    )
    return _requirement(
        f"{task}_development_decision",
        f"{task.title()} three-seed development decision and statistics",
        passed,
        evidence=(path,),
        details={
            "decision_passed": (value or {}).get("passed"),
            "expected_seeds": sorted(EXPECTED_SEEDS[task]),
            "observed_seeds": sorted(observed_seeds),
            "paired_comparisons": sorted(comparisons),
            "resource_seed_records": len(resources),
        },
    )


def _sealed_requirement(paths: ControlledPaths, task: str) -> dict[str, Any]:
    path = (
        paths.evaluation_root
        / "final"
        / task
        / "sealed_evaluation_receipt.json"
    )
    value = _optional_json(path)
    policy = (value or {}).get("policy", {})
    outputs = (value or {}).get("outputs", {})
    required_output_keys = {"predictions_path", "summary_path", "gate_path"}
    output_path_keys = {key for key in outputs if key.endswith("_path")}
    output_paths = [
        Path(outputs[key]) for key in sorted(required_output_keys) if key in outputs
    ]
    output_hashes_match = output_path_keys == required_output_keys and all(
        candidate.is_file()
        and outputs.get(f"{key.removesuffix('_path')}_sha256")
        == sha256_file(candidate)
        for key, candidate in (
            (key, Path(item))
            for key, item in outputs.items()
            if key.endswith("_path")
        )
    )
    claim = (value or {}).get("single_use_claim", {})
    claim_path_value = claim.get("path")
    claim_path = (
        Path(claim_path_value)
        if isinstance(claim_path_value, str) and claim_path_value
        else None
    )
    claim_value = _optional_json(claim_path) if claim_path else None
    claim_hash_matches = bool(claim_path and claim_path.is_file()) and claim.get(
        "sha256"
    ) == sha256_file(claim_path)
    receipt_decision = (value or {}).get("development_decision", {})
    claim_valid = bool(claim_value) and all(
        (
            claim_value.get("schema_version")
            == "studyhub.agent.sft.controlled_v2.sealed_claim.v1",
            claim_value.get("task") == task,
            claim_value.get("policy", {}).get("claim_is_single_use") is True,
            claim_value.get("policy", {}).get("claim_removed_after_failure") is False,
            claim_value.get("development_decision", {}).get("sha256")
            == receipt_decision.get("sha256"),
        )
    )
    passed = bool(value) and all(
        (
            value.get("schema_version")
            == "studyhub.agent.sft.controlled_v2.sealed_receipt.v2",
            value.get("evaluation_count") == 1,
            value.get("selected_before_sealed_evaluation") is True,
            policy.get("repeat_evaluation_allowed") is False,
            policy.get("sealed_result_used_for_model_selection") is False,
            (value.get("sealed_gate") or {}).get("passed") is True,
            claim_hash_matches,
            claim_valid,
            output_hashes_match,
        )
    )
    return _requirement(
        f"{task}_sealed_evaluation",
        f"{task.title()} single-use sealed evaluation",
        passed,
        evidence=(path, *((claim_path,) if claim_path else ()), *output_paths),
        details={
            "evaluation_count": (value or {}).get("evaluation_count"),
            "sealed_gate_passed": (value or {}).get("sealed_gate", {}).get("passed"),
            "claim_hash_matches": claim_hash_matches,
            "claim_valid": claim_valid,
            "output_hashes_match": output_hashes_match,
            "policy": policy,
        },
    )


def audit_completion(
    *, paths: ControlledPaths | None = None, include_report: bool = True
) -> dict[str, Any]:
    paths = paths or ControlledPaths()
    registry = _optional_json(paths.experiment_registry) or {}
    specs = [
        _spec(item)
        for section in (
            "initial_experiments",
            "reference_experiments",
            "dynamic_experiments",
        )
        for item in registry.get(section, [])
    ]
    dynamic = [_spec(item) for item in registry.get("dynamic_experiments", [])]
    counts: dict[str, int] = {}
    for spec in dynamic:
        counts[spec.stage] = counts.get(spec.stage, 0) + 1
    stage_counts_passed = all(
        counts.get(stage, 0) in allowed
        for stage, allowed in EXPECTED_DYNAMIC_COUNTS.items()
    )
    selection_stage_list = [
        str(item.get("stage")) for item in registry.get("selection_events", [])
    ]
    selection_stages = set(selection_stage_list)
    experiment_evidence = _experiment_evidence(paths, specs)
    contract_audit_path = paths.contract_dir / "audit.json"
    contract_audit = _optional_json(contract_audit_path) or {}
    prereg = _optional_json(paths.pre_registration) or {}
    tutor_human = contract_audit.get("tutor", {})
    challenge_review_path = (
        paths.contract_dir / "human_review/challenge_review_receipt.json"
    )
    challenge_review = _optional_json(challenge_review_path) or {}
    context_index_path = (
        paths.evaluation_root / "t-context/results/context_study_index.json"
    )
    context_index = _optional_json(context_index_path) or {}
    expected_context_results = {
        "chunks_1_output_768",
        "chunks_3_output_768",
        "chunks_5_output_768",
        "chunks_8_output_768",
        "tokens_2048_output_768",
        "tokens_4096_output_768",
        "tokens_8192_output_768",
        "tokens_4096_output_1024",
    }
    human_review_path = paths.evaluation_root / "final/human_review_receipt.json"
    human_review = _optional_json(human_review_path) or {}

    requirements = [
        _requirement(
            "frozen_contract",
            "Frozen challenge, prompt, Gate, token budget, leakage, and isolation contract",
            bool(contract_audit.get("passed"))
            and registry.get("contract_sha256") == contract_sha256()
            and prereg.get("contract_sha256") == contract_sha256()
            and contract_audit.get("isolation", {}).get("production_database_accessed")
            is False
            and contract_audit.get("isolation", {}).get("production_api_called")
            is False
            and contract_audit.get("isolation", {}).get("contains_paid_material")
            is False,
            evidence=(paths.pre_registration, paths.experiment_registry, contract_audit_path),
            details={
                "code_contract_sha256": contract_sha256(),
                "registry_contract_sha256": registry.get("contract_sha256"),
                "pre_registration_contract_sha256": prereg.get("contract_sha256"),
                "contract_audit_passed": contract_audit.get("passed"),
                "isolation": contract_audit.get("isolation"),
            },
        ),
        _requirement(
            "challenge_human_review",
            "Tutor challenge stratified and high-risk human review",
            challenge_review.get("human_review_completed") is True
            and challenge_review.get("all_records_approved") is True
            and challenge_review.get("high_risk_full_review_completed") is True,
            evidence=(
                paths.contract_dir / "tutor_human_review_packet_v2.jsonl",
                challenge_review_path,
            ),
            details={
                "packet_records": tutor_human.get("human_review_packet_records"),
                "packet_fraction": tutor_human.get("human_review_packet_fraction"),
                "human_review_completed": challenge_review.get(
                    "human_review_completed"
                ),
                "all_records_approved": challenge_review.get(
                    "all_records_approved"
                ),
                "high_risk_full_review_completed": challenge_review.get(
                    "high_risk_full_review_completed"
                ),
                "teacher_structural_reviewed": tutor_human.get(
                    "teacher_structural_reviewed"
                ),
            },
        ),
        _baseline_requirement(paths, "router"),
        _baseline_requirement(paths, "tutor"),
        _requirement(
            "selection_pipeline",
            "Pre-registered staged selection without sealed-test reads",
            selection_stages == EXPECTED_SELECTION_STAGES
            and len(selection_stage_list) == len(EXPECTED_SELECTION_STAGES)
            and all(
                item.get("sealed_data_read") is False
                for item in registry.get("selection_events", [])
            ),
            evidence=(paths.experiment_registry,),
            details={
                "expected_stages": sorted(EXPECTED_SELECTION_STAGES),
                "observed_stages": selection_stage_list,
            },
        ),
        _requirement(
            "registered_experiment_matrix",
            "Complete controlled experiment matrix with expected one-factor arms",
            stage_counts_passed,
            evidence=(paths.experiment_registry,),
            details={
                "observed_dynamic_stage_counts": counts,
                "expected_dynamic_stage_counts": {
                    key: sorted(value) for key, value in EXPECTED_DYNAMIC_COUNTS.items()
                },
            },
        ),
        _requirement(
            "experiment_artifacts",
            "Every registered arm has a complete adapter, telemetry, and development Gate",
            bool(specs)
            and experiment_evidence["all_adapters_exist"]
            and experiment_evidence["all_telemetry_exists"]
            and experiment_evidence["all_training_succeeded"]
            and experiment_evidence["all_evaluated"],
            evidence=(paths.evaluation_root / "result_index.json",),
            details=experiment_evidence,
        ),
        _ablation_requirement(paths, "router"),
        _ablation_requirement(paths, "tutor"),
        _requirement(
            "tutor_context_study",
            "Tutor chunk-count, token-bucket, and output-budget inference study",
            bool(context_index) and expected_context_results.issubset(context_index),
            evidence=(context_index_path,),
            details={
                "expected_results": sorted(expected_context_results),
                "observed_results": sorted(context_index),
            },
        ),
        _final_requirement(paths, "router"),
        _final_requirement(paths, "tutor"),
        _requirement(
            "final_blind_human_review",
            "Final 120-item blinded human review with adjudication",
            bool(human_review)
            and human_review.get("completed") is True
            and int(human_review.get("records", 0)) == 120
            and human_review.get("blinded") is True
            and human_review.get("adjudication_completed") is True
            and human_review.get("all_records_approved") is True,
            evidence=(human_review_path,),
            details=human_review,
        ),
        _sealed_requirement(paths, "router"),
        _sealed_requirement(paths, "tutor"),
    ]

    if include_report:
        report = (
            paths.project_root
            / "reports/STUDYHUB_SFT_COMPLETION_REPORT.html"
        )
        manifest_path = paths.evaluation_root / "final/completion_report_manifest.json"
        manifest = _optional_json(manifest_path) or {}
        requirements.append(
            _requirement(
                "completion_report",
                "HTML report generated exclusively from controlled-v2 evidence",
                report.is_file()
                and manifest.get("contract_sha256") == contract_sha256()
                and manifest.get("report_sha256") == sha256_file(report),
                evidence=(report, manifest_path),
                details={
                    "manifest_contract_sha256": manifest.get("contract_sha256"),
                    "report_hash_matches": (
                        report.is_file()
                        and manifest.get("report_sha256") == sha256_file(report)
                    ),
                },
            )
        )

    passed = all(item["passed"] for item in requirements)
    result = {
        "schema_version": "studyhub.agent.sft.controlled_v2.completion_audit.v1",
        "passed": passed,
        "requirements_total": len(requirements),
        "requirements_passed": sum(item["passed"] for item in requirements),
        "requirements_failed": [
            item["id"] for item in requirements if not item["passed"]
        ],
        "requirements": requirements,
    }
    destination = paths.evaluation_root / "final/completion_audit.json"
    _write_json(destination, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--without-report", action="store_true")
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    result = audit_completion(include_report=not args.without_report)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if args.require_complete and not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
