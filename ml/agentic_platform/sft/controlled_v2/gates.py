"""Pre-registered hard gates for controlled-v2 development evaluations."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .contract import ROUTER_GATE, TUTOR_GATE


def _rate(summary: Mapping[str, Any], metric: str) -> float:
    value = summary["metrics"][metric]["rate"]
    return float(value) if value is not None else 0.0


def gate_router(
    raw: Mapping[str, Any], projection: Mapping[str, Any]
) -> dict[str, Any]:
    actual = {
        "json_valid": _rate(raw, "json_valid"),
        "contract_valid": _rate(raw, "contract_valid"),
        "tool_required_name": _rate(raw, "tool_required_name"),
        "mode_correct": _rate(raw, "mode_correct"),
        "material_id_exact": _rate(raw, "material_id_exact"),
        "page_exact": _rate(raw, "page_exact"),
        "force_final_compliant": _rate(raw, "force_final_compliant"),
        "injection_permission_safety": _rate(raw, "injection_permission_safety"),
        "task_family_floor": float(raw.get("task_family_floor") or 0.0),
        "projection_correction_rate": float(
            projection.get("projection_correction_rate") or 0.0
        ),
    }
    minimums = {
        key: value
        for key, value in ROUTER_GATE.items()
        if not key.endswith("_max")
        and key not in {"cross_seed_primary_std_max", "legacy_regression_pp_max"}
    }
    failures = {
        key: {"actual": actual[key], "required": threshold, "operator": ">="}
        for key, threshold in minimums.items()
        if actual[key] < threshold
    }
    maximum = ROUTER_GATE["projection_correction_rate_max"]
    if actual["projection_correction_rate"] > maximum:
        failures["projection_correction_rate"] = {
            "actual": actual["projection_correction_rate"],
            "required": maximum,
            "operator": "<=",
        }
    # Screening advances safe candidates for parameter attribution; JSON and
    # contract quality remain mandatory in the unchanged full Gate.
    safety_keys = {"injection_permission_safety"}
    safety_failures = {
        key: value for key, value in failures.items() if key in safety_keys
    }
    return {
        "schema_version": "studyhub.agent.sft.controlled_v2.router_gate.v1",
        "passed": not failures,
        "actual": actual,
        "thresholds": ROUTER_GATE,
        "failures": failures,
        "screening_eligible": not safety_failures,
        "screening_safety_failures": safety_failures,
        "selection_metric": "strict_route_pass",
        "selection_score": _rate(raw, "strict_route_pass"),
    }


def gate_tutor(summary: Mapping[str, Any]) -> dict[str, Any]:
    actual = {
        "strict_grounded_pass": _rate(summary, "strict_grounded_pass"),
        "citation_exact": _rate(summary, "citation_exact"),
        "citation_entailment": _rate(summary, "citation_entailment"),
        "no_answer_abstention": _rate(summary, "no_answer_abstention"),
        "conflict_disclosure": _rate(summary, "conflict_disclosure"),
        "unsupported_claim_rate": 1.0 - _rate(summary, "unsupported_claim_free"),
        "no_tool_actions": _rate(summary, "no_tool_actions"),
        "sensitive_output_free": _rate(summary, "sensitive_output_free"),
    }
    minimum_keys = (
        "strict_grounded_pass",
        "citation_exact",
        "citation_entailment",
        "no_answer_abstention",
        "conflict_disclosure",
        "no_tool_actions",
        "sensitive_output_free",
    )
    failures = {
        key: {"actual": actual[key], "required": TUTOR_GATE[key], "operator": ">="}
        for key in minimum_keys
        if actual[key] < TUTOR_GATE[key]
    }
    if actual["unsupported_claim_rate"] > TUTOR_GATE["unsupported_claim_rate_max"]:
        failures["unsupported_claim_rate"] = {
            "actual": actual["unsupported_claim_rate"],
            "required": TUTOR_GATE["unsupported_claim_rate_max"],
            "operator": "<=",
        }
    safety_keys = {"no_tool_actions", "sensitive_output_free"}
    safety_failures = {
        key: value for key, value in failures.items() if key in safety_keys
    }
    return {
        "schema_version": "studyhub.agent.sft.controlled_v2.tutor_gate.v1",
        "passed": not failures,
        "actual": actual,
        "thresholds": TUTOR_GATE,
        "failures": failures,
        "screening_eligible": not safety_failures,
        "screening_safety_failures": safety_failures,
        "selection_metric": "strict_grounded_pass",
        "selection_score": actual["strict_grounded_pass"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", choices=("router", "tutor"))
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--projection-comparison", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fail-on-gate", action="store_true")
    args = parser.parse_args()
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    if args.task == "router":
        if args.projection_comparison is None:
            parser.error("Router gate requires --projection-comparison")
        projection = json.loads(args.projection_comparison.read_text(encoding="utf-8"))
        result = gate_router(summary, projection)
    else:
        result = gate_tutor(summary)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if args.fail_on_gate and not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
