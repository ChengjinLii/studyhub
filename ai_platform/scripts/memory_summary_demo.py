from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


AI_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AI_PLATFORM_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_platform.feedback.processor import FeedbackEvent
from ai_platform.memory.llm_summarizer import LLMMemorySummarizer, MockMemorySummarizer
from ai_platform.serving.llm_provider import get_env_chat_provider


def run_memory_summary(
    *,
    hook: str = "useful",
    note: str = "计划有帮助",
    recommended_item_ids: list[str] | None = None,
    use_api: bool = False,
) -> dict[str, object]:
    provider = get_env_chat_provider() if use_api else None
    summarizer = LLMMemorySummarizer(provider) if provider else MockMemorySummarizer()
    result = summarizer.summarize_feedback(
        [FeedbackEvent(hook=hook, note=note, selected_item_ids=tuple(recommended_item_ids or []))],
        recommended_item_ids=recommended_item_ids or ["material-001"],
    )
    return result.to_dict()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run isolated StudyHub feedback -> Hermes summary demo.")
    parser.add_argument("--hook", default="useful")
    parser.add_argument("--note", default="计划有帮助")
    parser.add_argument("--item-id", action="append", dest="item_ids", default=[])
    parser.add_argument("--use-api", action="store_true", help="Use STUDYHUB_LLM_* env vars if configured.")
    args = parser.parse_args()
    print(json.dumps(run_memory_summary(hook=args.hook, note=args.note, recommended_item_ids=args.item_ids, use_api=args.use_api), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
