from __future__ import annotations

from pathlib import Path

from scripts.benchmark.build_open_only_sft_portfolio import build_portfolio

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_current_portfolio_is_ready_but_has_no_candidate_or_external_scores() -> None:
    result = build_portfolio(PROJECT_ROOT)

    assert result["status"] == "READY_BUT_NOT_RUN"
    assert result["benchmark"]["sealed_used"] is False
    assert result["internal"]["development"]["base"]["status"] == "COMPLETED"
    assert result["internal"]["development"]["mixed_v3_0"]["status"] == "COMPLETED"
    assert result["internal"]["development"]["open_only_v1_1"]["status"] == "NOT_RUN"
    assert all(
        row["model_results"]["open_only_v1_1"]["status"]
        in {"NOT_RUN", "LICENSE_REVIEW_REQUIRED"}
        for row in result["external"].values()
    )
    assert result["result_policy"]["aggregate_agent_score"] == "PROHIBITED"
