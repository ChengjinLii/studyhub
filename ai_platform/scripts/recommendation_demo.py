from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


AI_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AI_PLATFORM_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_platform.recommendation.explainable_ranker import ExplainableRanker, load_recommendation_fixture


DEFAULT_SAMPLE_PATH = AI_PLATFORM_ROOT / "data" / "sample_recommendation_fixture.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run isolated explainable StudyHub ranking demos.")
    parser.add_argument("--sample-path", type=Path, default=DEFAULT_SAMPLE_PATH)
    parser.add_argument("--scenario", choices=["home", "market", "contributors"], default="home")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    raw = json.loads(args.sample_path.read_text(encoding="utf-8"))
    user, items, contributors = load_recommendation_fixture(raw)
    ranker = ExplainableRanker()
    if args.scenario == "home":
        results = [item.to_dict() for item in ranker.rank_home_materials(items, user, top_k=args.top_k)]
    elif args.scenario == "market":
        results = [item.to_dict() for item in ranker.rank_market_items(items, user, top_k=args.top_k)]
    else:
        results = [item.to_dict() for item in ranker.rank_contributors(contributors, top_k=args.top_k)]
    print(json.dumps({"scenario": args.scenario, "results": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
