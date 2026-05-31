from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


AI_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AI_PLATFORM_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_platform.feedback.processor import FeedbackEvent, FeedbackProcessor
from ai_platform.memory.store import JsonHermesMemoryStore
from ai_platform.scripts.studycopilot_demo import DEFAULT_SAMPLE_PATH, run_studycopilot
from ai_platform.retrieval.semantic_search import InMemorySemanticSearch
from ai_platform.scripts.semantic_search_demo import load_documents
from ai_platform.agents.genrec_agent import GenRecAgent


DEFAULT_MEMORY_PATH = AI_PLATFORM_ROOT / "data" / "demo_hermes_memory.local.json"


def run_feedback_memory_demo(
    query: str,
    *,
    hook: str,
    note: str = "",
    memory_path: Path = DEFAULT_MEMORY_PATH,
    user_memory_enabled: bool = True,
) -> dict[str, object]:
    searcher = InMemorySemanticSearch(load_documents(DEFAULT_SAMPLE_PATH))
    response = GenRecAgent(searcher).run(query)
    selected_ids = tuple(item["id"] for item in response.recommended_items[:1])
    store = JsonHermesMemoryStore(memory_path)
    store.set_user_memory_enabled(user_memory_enabled, clear_existing=not user_memory_enabled)
    stored = FeedbackProcessor(store).process(
        response,
        FeedbackEvent(hook=hook, note=note, selected_item_ids=selected_ids),
    )
    return {
        "response": response.to_dict(),
        "feedback": {"hook": hook, "selectedItemIds": list(selected_ids)},
        "preferences": {"userMemoryEnabled": store.user_memory_enabled()},
        "storedMemories": [memory.to_dict() for memory in stored],
        "memoryPath": str(memory_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run isolated StudyCopilot feedback -> Hermes memory demo.")
    parser.add_argument("query", nargs="?", default="我两周后考通信原理，基础一般，想找速成资料和真题解析。")
    parser.add_argument("--hook", default="useful", choices=sorted(["useful", "not_useful", "too_easy", "too_hard", "not_relevant"]))
    parser.add_argument("--note", default="")
    parser.add_argument("--memory-path", type=Path, default=DEFAULT_MEMORY_PATH)
    parser.add_argument("--disable-user-memory", action="store_true", help="Do not store user-scope memory candidates.")
    args = parser.parse_args()
    print(
        json.dumps(
            run_feedback_memory_demo(
                args.query,
                hook=args.hook,
                note=args.note,
                memory_path=args.memory_path,
                user_memory_enabled=not args.disable_user_memory,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
