from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


AI_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AI_PLATFORM_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_platform.agents.genrec_agent import GenRecAgent
from ai_platform.evaluation.studycopilot_eval import StudyCopilotEvalRunner
from ai_platform.retrieval.semantic_search import InMemorySemanticSearch
from ai_platform.scripts.semantic_search_demo import DEFAULT_SAMPLE_PATH, load_documents


def run_eval(*, sample_path: Path = DEFAULT_SAMPLE_PATH) -> dict[str, object]:
    searcher = InMemorySemanticSearch(load_documents(sample_path))
    return StudyCopilotEvalRunner(GenRecAgent(searcher)).run()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run StudyCopilot v9 offline acceptance evaluation.")
    parser.add_argument("--sample-path", type=Path, default=DEFAULT_SAMPLE_PATH)
    args = parser.parse_args()
    report = run_eval(sample_path=args.sample_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
