from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


AI_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AI_PLATFORM_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_platform.retrieval.semantic_search import InMemorySemanticSearch, SearchDocument


DEFAULT_SAMPLE_PATH = AI_PLATFORM_ROOT / "data" / "sample_documents.json"


def load_documents(path: Path) -> list[SearchDocument]:
    raw_items = json.loads(path.read_text(encoding="utf-8"))
    return [
        SearchDocument(
            id=str(item["id"]),
            type=str(item["type"]),
            title=str(item["title"]),
            text=str(item["text"]),
            metadata=dict(item.get("metadata") or {}),
        )
        for item in raw_items
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run isolated mock semantic search over StudyHub sample documents.")
    parser.add_argument("query", nargs="?", default="通信原理期末怎么复习", help="Natural language query to search for.")
    parser.add_argument("--top-k", type=int, default=5, help="Number of results to return.")
    parser.add_argument("--type", dest="type_filter", choices=["material", "column", "request"], help="Optional document type filter.")
    parser.add_argument("--mode", choices=["dense", "sparse", "hybrid"], default="hybrid", help="Retrieval strategy to run.")
    parser.add_argument("--sample-path", type=Path, default=DEFAULT_SAMPLE_PATH, help="Path to sample document JSON.")
    args = parser.parse_args()

    documents = load_documents(args.sample_path)
    searcher = InMemorySemanticSearch(documents)
    results = searcher.search(args.query, top_k=args.top_k, type_filter=args.type_filter, mode=args.mode)

    print(
        json.dumps(
            {"query": args.query, "mode": args.mode, "results": [result.to_dict() for result in results]},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
