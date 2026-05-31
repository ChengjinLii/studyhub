from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


AI_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AI_PLATFORM_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_platform.router.query_suggestion import LLMQuerySuggestionProvider, MockQuerySuggestionProvider
from ai_platform.serving.llm_provider import get_env_chat_provider


def run_query_suggestion(query: str, *, limit: int = 5, use_api: bool = False) -> dict[str, object]:
    provider = get_env_chat_provider() if use_api else None
    suggester = LLMQuerySuggestionProvider(provider) if provider else MockQuerySuggestionProvider()
    return suggester.suggest(query, limit=limit).to_dict()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run isolated StudyHub query suggestion demo.")
    parser.add_argument("query", nargs="?", default="通信原理")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--use-api", action="store_true", help="Use STUDYHUB_LLM_* env vars if configured.")
    args = parser.parse_args()
    print(json.dumps(run_query_suggestion(args.query, limit=args.limit, use_api=args.use_api), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
