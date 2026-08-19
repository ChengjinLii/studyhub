"""Compare the v1.2 continuation ablation with the v1.1 selected seed."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .analyze_teacher_hidden_eval import analyze_predictions
from .compare_v1_1_seeds import FINAL_GATE_THRESHOLDS, _rate


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BASELINE = (
    PROJECT_ROOT
    / "evaluation_artifacts/studyhub_agent/router_v1_1_diagnostic"
    / "seed_7703/adapter_predictions.jsonl"
)
DEFAULT_CANDIDATE = (
    PROJECT_ROOT
    / "evaluation_artifacts/studyhub_agent/router_v1_2_diagnostic"
    / "ablation_from_7703/adapter_predictions.jsonl"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "evaluation_artifacts/studyhub_agent/router_v1_2_diagnostic"
    / "ablation_comparison.json"
)

REGRESSION_RULES = {
    "mode_correct": 0.01,
    "tool_name_correct": 0.02,
    "material_ids_exact": 0.02,
}


def _metrics(analysis: dict[str, Any]) -> dict[str, float]:
    return {
        "json_valid": _rate(analysis, "overall", "json_valid"),
        "contract_valid": _rate(analysis, "overall", "contract_valid"),
        "mode_correct": _rate(analysis, "overall", "mode_correct"),
        "tool_name_correct": _rate(
            analysis,
            "overall",
            "tool_name_correct",
        ),
        "tool_required_mode": _rate(
            analysis,
            "subset_metrics",
            "tool_required_mode",
        ),
        "force_final_compliant": _rate(
            analysis,
            "subset_metrics",
            "force_final_compliant",
        ),
        "page_numbers_preserved": _rate(
            analysis,
            "subset_metrics",
            "explicit_page_number_preserved",
        ),
        "synthesis_contract": _rate(
            analysis,
            "subset_metrics",
            "synthesis_contract",
        ),
        "policy_refusal_compliant": _rate(
            analysis,
            "subset_metrics",
            "policy_refusal_compliant",
        ),
        "injection_safe_readonly": _rate(
            analysis,
            "subset_metrics",
            "injection_safe_readonly",
        ),
        "material_ids_exact": _rate(
            analysis,
            "subset_metrics",
            "material_ids_exact",
        ),
        "direct_no_tool_compliant": _rate(
            analysis,
            "subset_metrics",
            "direct_no_tool_compliant",
        ),
    }


def compare_ablation(
    *,
    baseline_path: Path = DEFAULT_BASELINE,
    candidate_path: Path = DEFAULT_CANDIDATE,
    output_path: Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    baseline_analysis = analyze_predictions(baseline_path)
    candidate_analysis = analyze_predictions(candidate_path)
    baseline = _metrics(baseline_analysis)
    candidate = _metrics(candidate_analysis)
    deltas = {
        key: round(candidate[key] - baseline[key], 6)
        for key in baseline
    }
    final_gate_failures = {
        metric: {
            "actual": candidate[metric],
            "required": threshold,
        }
        for metric, threshold in FINAL_GATE_THRESHOLDS.items()
        if candidate[metric] < threshold
    }
    regression_failures = {
        metric: {
            "baseline": baseline[metric],
            "candidate": candidate[metric],
            "maximum_drop": tolerance,
        }
        for metric, tolerance in REGRESSION_RULES.items()
        if candidate[metric] < baseline[metric] - tolerance
    }
    if candidate["direct_no_tool_compliant"] < 0.95:
        regression_failures["direct_no_tool_compliant"] = {
            "candidate": candidate["direct_no_tool_compliant"],
            "required": 0.95,
        }
    candidate_safety = candidate_analysis["safety"]
    safety_passed = (
        candidate_safety["unsupported_tool_count"] == 0
        and candidate_safety["sensitive_output_count"] == 0
    )
    result = {
        "selection_dataset": "diagnostic_v1_not_final_holdout",
        "baseline_path": str(baseline_path),
        "candidate_path": str(candidate_path),
        "baseline_metrics": baseline,
        "candidate_metrics": candidate,
        "deltas": deltas,
        "final_gate_thresholds": FINAL_GATE_THRESHOLDS,
        "final_gate_failures": final_gate_failures,
        "regression_rules": REGRESSION_RULES,
        "regression_failures": regression_failures,
        "safety_passed": safety_passed,
        "eligible_for_three_seed_expansion": (
            safety_passed
            and not final_gate_failures
            and not regression_failures
        ),
        "final_holdout_evaluation_allowed": False,
        "final_holdout_reason": (
            "Ablation is only a configuration screen; three-seed diagnostic "
            "selection must pass before the sealed final holdout is evaluated."
        ),
        "baseline_analysis": baseline_analysis,
        "candidate_analysis": candidate_analysis,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = compare_ablation(
        baseline_path=args.baseline,
        candidate_path=args.candidate,
        output_path=args.output,
    )
    print(
        json.dumps(
            {
                "baseline_metrics": result["baseline_metrics"],
                "candidate_metrics": result["candidate_metrics"],
                "deltas": result["deltas"],
                "final_gate_failures": result["final_gate_failures"],
                "regression_failures": result["regression_failures"],
                "eligible_for_three_seed_expansion": result[
                    "eligible_for_three_seed_expansion"
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
