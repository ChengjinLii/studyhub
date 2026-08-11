from __future__ import annotations

from copy import deepcopy

from ml.agentic_platform.sft.gate_grounded_tutor import (
    CRITICAL_BOUNDARY_FAMILIES,
    THRESHOLDS,
    gate_grounded_summary,
)


def _summary(rate: float = 1.0) -> dict:
    metric = {"passed": 120, "total": 120, "rate": rate}
    family_metric = {"passed": 12, "total": 12, "rate": rate}
    families = {
        family: {
            "boundary_compliant": deepcopy(family_metric),
            "strict_grounded_pass": deepcopy(family_metric),
        }
        for family in CRITICAL_BOUNDARY_FAMILIES
    }
    families["page_explanation_v1"] = {
        "boundary_compliant": deepcopy(family_metric),
        "strict_grounded_pass": deepcopy(family_metric),
    }
    return {
        "records": 120,
        "splits": ["validation"],
        "metrics": {name: deepcopy(metric) for name in THRESHOLDS},
        "family_metrics": families,
        "answer_bigram_f1_mean": 0.51,
    }


def test_grounded_gate_passes_only_full_generation_contract() -> None:
    assert gate_grounded_summary(_summary())["passed"] is True

    failing = _summary()
    failing["metrics"]["citations_exact"]["rate"] = 0.90
    result = gate_grounded_summary(failing)
    assert result["passed"] is False
    assert result["metric_failures"] == {
        "citations_exact": {"actual": 0.9, "required": 0.95}
    }


def test_grounded_gate_checks_boundary_families_and_split() -> None:
    failing = _summary()
    failing["family_metrics"]["untrusted_observation_v1"][
        "boundary_compliant"
    ]["rate"] = 0.80
    result = gate_grounded_summary(failing)
    assert result["passed"] is False
    assert "untrusted_observation_v1" in result["critical_boundary_failures"]

    wrong_split = _summary()
    wrong_split["splits"] = ["test"]
    result = gate_grounded_summary(wrong_split)
    assert result["passed"] is False
    assert result["selection_valid"] is False
