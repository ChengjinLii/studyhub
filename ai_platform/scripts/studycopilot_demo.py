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
from ai_platform.retrieval.semantic_search import InMemorySemanticSearch
from ai_platform.router.query_understanding import LLMQueryUnderstandingRouter
from ai_platform.scripts.semantic_search_demo import DEFAULT_SAMPLE_PATH, load_documents
from ai_platform.serving.llm_provider import get_env_chat_provider
from ai_platform.serving.rerank_provider import ChatRerankProvider


def run_studycopilot(
    query: str,
    *,
    sample_path: Path = DEFAULT_SAMPLE_PATH,
    top_k: int = 5,
    use_api: bool = False,
) -> dict[str, object]:
    searcher = InMemorySemanticSearch(load_documents(sample_path))
    provider = get_env_chat_provider() if use_api else None
    router = LLMQueryUnderstandingRouter(provider) if provider else None
    reranker = ChatRerankProvider(provider) if provider else None
    return GenRecAgent(searcher, router=router, reranker=reranker, chat_provider=provider).run(query, top_k=top_k).to_dict()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run isolated StudyHub AI StudyCopilot v9 demo.")
    parser.add_argument("query", nargs="?", default="我两周后考通信原理，基础一般，想找速成资料和真题解析。")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--sample-path", type=Path, default=DEFAULT_SAMPLE_PATH)
    parser.add_argument("--use-api", action="store_true", help="Use STUDYHUB_LLM_* env vars for Router and composition.")
    args = parser.parse_args()
    print(
        json.dumps(
            run_studycopilot(args.query, sample_path=args.sample_path, top_k=args.top_k, use_api=args.use_api),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
