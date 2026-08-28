from __future__ import annotations

from scripts.train.decide_open_only_sft_promotion import decide


def _control(*, recovery: bool = True) -> dict:
    return {
        "hard_control_failures": [],
        "provenance_failures": [],
        "runtime_correction_diff": {
            "status": (
                "SEMANTIC_EQUIVALENCE_CONFIRMED_BY_R1_R4"
                if recovery
                else "REQUIRES_R1_R4_CONFIRMATION"
            ),
            "recovery_contract": {
                "eligible": recovery,
                "r4_status": "BITWISE_RESUME_PASS" if recovery else None,
            },
        },
        "scope": {"sealed_used": False},
    }


def _portfolio(*, external: str = "COMPLETED") -> dict:
    completed = {"status": "COMPLETED"}
    return {
        "training": {"open_only_v1_1": {"status": "COMPLETE"}},
        "internal": {
            "development": {
                "base": completed,
                "mixed_v3_0": completed,
                "open_only_v1_1": completed,
            },
            "variance": {
                "base": completed,
                "mixed_v3_0": completed,
                "open_only_v1_1": completed,
            },
        },
        "external": {
            benchmark: {
                "model_results": {
                    role: {"status": external}
                    for role in ("base", "mixed_v3_0", "open_only_v1_1")
                }
            }
            for benchmark in ("bfcl", "tau2")
        },
        "promotion_signals": {
            name: {"status": "PASS"}
            for name in (
                "internal_paired_direction",
                "capability_tradeoffs",
                "cost_latency",
                "variance_direction",
                "external_direction",
            )
        },
        "scope": {"sealed_used": False},
    }


def test_external_not_run_blocks_promotion() -> None:
    result = decide(_control(), _portfolio(external="NOT_RUN"))

    assert result["decision"] == "BLOCKED_PENDING_EXTERNAL_EVIDENCE"
    assert result["requirements"]["external_bfcl_tau2"]["status"] == "NOT_RUN"


def test_recovery_failure_precedes_all_model_evaluation() -> None:
    result = decide(_control(recovery=False), _portfolio())

    assert result["decision"] == "BLOCKED_RECOVERY_CONTRACT"


def test_sealed_access_fails_closed() -> None:
    portfolio = _portfolio()
    portfolio["scope"]["sealed_used"] = True

    result = decide(_control(), portfolio)

    assert result["decision"] == "BLOCKED_CONTROL_DRIFT"


def test_complete_portfolio_is_ready_for_final_freeze_not_sealed_result() -> None:
    result = decide(_control(), _portfolio())

    assert result["decision"] == "CANDIDATE_READY_FOR_FINAL_FREEZE"
    assert "Sealed remains unused" in result["claim_boundary"]
