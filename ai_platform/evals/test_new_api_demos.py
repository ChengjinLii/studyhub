from __future__ import annotations

from pathlib import Path
import sys


AI_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AI_PLATFORM_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_platform.scripts.memory_summary_demo import run_memory_summary
from ai_platform.scripts.moderation_advisor_demo import run_moderation_advisor
from ai_platform.scripts.query_suggestion_demo import run_query_suggestion
from ai_platform.scripts.question_tutor_demo import run_question_tutor, select_question_tutor_candidates
from ai_platform.retrieval.semantic_search import InMemorySemanticSearch
from ai_platform.scripts.semantic_search_demo import DEFAULT_SAMPLE_PATH, load_documents


def test_query_suggestion_demo_returns_suggestions() -> None:
    result = run_query_suggestion("通信原理", limit=3)

    assert len(result["suggestions"]) == 3


def test_question_tutor_demo_returns_response_and_candidates() -> None:
    result = run_question_tutor("这道链表题为什么我写错了？")

    assert result["response"]["explanation"]
    assert result["candidates"]
    assert all(
        "链表" in candidate["title"] or "数据结构" in candidate["title"]
        for candidate in result["candidates"]
    )


def test_moderation_advisor_demo_pairs_decisions_with_advice() -> None:
    result = run_moderation_advisor(material_id="material-reject-001")

    assert result["items"][0]["decision"]["action"] == "REJECT"
    assert result["items"][0]["advice"]["suggestedAction"] == "REJECT"


def test_memory_summary_demo_returns_candidates() -> None:
    result = run_memory_summary(note="真题解析有帮助", recommended_item_ids=["material-001"])

    assert result["candidates"]


def test_question_tutor_candidate_selector_prefers_lexically_relevant_hits() -> None:
    searcher = InMemorySemanticSearch(load_documents(DEFAULT_SAMPLE_PATH))
    candidates = select_question_tutor_candidates(searcher.search("这道链表题为什么我写错了？", top_k=8, mode="hybrid"), "这道链表题为什么我写错了？")

    assert candidates
    assert all("链表" in candidate.document.searchable_text or "数据结构" in candidate.document.searchable_text for candidate in candidates)
