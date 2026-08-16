from __future__ import annotations

from copy import deepcopy

from ml.agentic_platform.sft.gate_router_rl_readiness import assess_rl_readiness


def _gate() -> dict:
    return {
        "passed": True,
        "required_variants": ["raw", "normalized"],
        "final_holdout_read": False,
        "variants": {"raw": {"passed": True}, "normalized": {"passed": True}},
    }


def _manifest() -> dict:
    return {
        "adapter_sha256": "a" * 64,
        "dataset_sha256": "b" * 64,
        "production_api_called": False,
        "production_database_accessed": False,
        "final_holdout_read": False,
        "decoding": {
            "typed_constrained_projection": True,
            "deterministic_argument_protection": True,
        },
    }


def test_rl_readiness_requires_isolated_constrained_dual_path_gate() -> None:
    result = assess_rl_readiness(
        production_gate=_gate(),
        run_manifest=_manifest(),
    )

    assert result["ready_for_offline_rl_pilot"] is True
    assert result["ready_for_production_rollout"] is False
    assert result["blockers"] == []


def test_rl_readiness_reports_exact_blockers() -> None:
    gate = deepcopy(_gate())
    manifest = deepcopy(_manifest())
    gate["variants"]["normalized"]["passed"] = False
    manifest["production_database_accessed"] = True
    manifest["decoding"]["deterministic_argument_protection"] = False

    result = assess_rl_readiness(
        production_gate=gate,
        run_manifest=manifest,
    )

    assert result["ready_for_offline_rl_pilot"] is False
    assert result["blockers"] == [
        "deterministic_argument_protection_enabled",
        "production_database_not_accessed",
        "raw_and_normalized_passed",
    ]
