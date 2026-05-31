from __future__ import annotations

import json
from pathlib import Path
import sys


AI_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AI_PLATFORM_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_platform.recommendation.explainable_ranker import ExplainableRanker, load_recommendation_fixture


SAMPLE_PATH = AI_PLATFORM_ROOT / "data" / "sample_recommendation_fixture.json"


def test_home_ranking_prefers_relevant_low_risk_content() -> None:
    user, items, _ = load_recommendation_fixture(json.loads(SAMPLE_PATH.read_text(encoding="utf-8")))

    results = ExplainableRanker().rank_home_materials(items, user, top_k=3)

    assert results
    assert results[0].item.id == "material-001"
    assert all(result.item.id != "material-risk-001" for result in results[:2])
    assert results[0].components["interest"] > 0
    assert results[0].reasons


def test_market_ranking_demotes_sold_items() -> None:
    user, items, _ = load_recommendation_fixture(json.loads(SAMPLE_PATH.read_text(encoding="utf-8")))

    results = ExplainableRanker().rank_market_items(items, user, top_k=3)

    assert results[0].item.id == "market-001"
    assert results[-1].item.id == "market-003"
    assert results[-1].components["status_penalty"] < 0


def test_contributor_ranking_penalizes_upheld_reports() -> None:
    _, _, contributors = load_recommendation_fixture(json.loads(SAMPLE_PATH.read_text(encoding="utf-8")))

    results = ExplainableRanker().rank_contributors(contributors, top_k=3)

    assert results[0].contributor.id == "uploader-003"
    risky = next(result for result in results if result.contributor.id == "uploader-002")
    assert risky.components["riskPenalty"] < 0
