from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


AI_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AI_PLATFORM_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_platform.router.query_understanding import LLMQueryUnderstandingRouter, MockQueryUnderstandingRouter
from ai_platform.serving.llm_provider import get_env_chat_provider


def run_query_understanding(query: str, *, use_api: bool = False) -> dict[str, object]:
    provider = get_env_chat_provider() if use_api else None
    router = LLMQueryUnderstandingRouter(provider) if provider else MockQueryUnderstandingRouter()
    result = router.understand(query)
    return result.to_dict()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run isolated StudyHub query understanding demo.")
    parser.add_argument("query", nargs="?", default="我两周后考通信原理，基础一般，想找速成资料和真题解析。")
    parser.add_argument("--use-api", action="store_true", help="Use STUDYHUB_LLM_* env vars if configured.")
    args = parser.parse_args()
    print(json.dumps(run_query_understanding(args.query, use_api=args.use_api), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
