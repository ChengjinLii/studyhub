from __future__ import annotations

from pathlib import Path
import sys


AI_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AI_PLATFORM_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_platform.agents.genrec_agent import GenRecAgent
from ai_platform.feedback.processor import FeedbackEvent, FeedbackProcessor
from ai_platform.memory.store import JsonHermesMemoryStore
from ai_platform.retrieval.semantic_search import InMemorySemanticSearch
from ai_platform.scripts.feedback_memory_demo import run_feedback_memory_demo
from ai_platform.scripts.semantic_search_demo import DEFAULT_SAMPLE_PATH, load_documents


def _response():
    searcher = InMemorySemanticSearch(load_documents(DEFAULT_SAMPLE_PATH))
    return GenRecAgent(searcher).run("我两周后考通信原理，基础一般，想找速成资料和真题解析。")


def test_feedback_processor_stores_sanitized_memory_candidates(tmp_path: Path) -> None:
    response = _response()
    selected_id = response.recommended_items[0]["id"]
    store = JsonHermesMemoryStore(tmp_path / "memory.json")

    stored = FeedbackProcessor(store).process(
        response,
        FeedbackEvent(
            hook="useful",
            note="这个计划有用，可以联系我 13812345678",
            selected_item_ids=(selected_id, "made-up-id"),
        ),
    )

    memories = store.list_memories()
    values = [memory.candidate.value for memory in memories]
    assert stored
    assert "useful" in values
    assert any("[REDACTED_CONTACT]" in value for value in values)
    assert any(
        memory.candidate.key == "positive_or_negative_feedback_items" and memory.candidate.value == selected_id
        for memory in memories
    )
    assert all("made-up-id" not in memory.candidate.value for memory in memories)


def test_feedback_processor_rejects_unsupported_hook(tmp_path: Path) -> None:
    processor = FeedbackProcessor(JsonHermesMemoryStore(tmp_path / "memory.json"))

    try:
        processor.process(_response(), FeedbackEvent(hook="delete_everything"))
    except ValueError as exc:
        assert "unsupported feedback hook" in str(exc)
    else:
        raise AssertionError("unsupported feedback hook should fail")


def test_memory_store_upsert_and_delete(tmp_path: Path) -> None:
    response = _response()
    store = JsonHermesMemoryStore(tmp_path / "memory.json")
    processor = FeedbackProcessor(store)

    processor.process(response, FeedbackEvent(hook="useful"))
    processor.process(response, FeedbackEvent(hook="useful"))
    useful_memory = next(memory for memory in store.list_memories() if memory.candidate.key == "last_feedback_hook")

    assert useful_memory.event_count == 2
    assert store.delete_memory(useful_memory.id)
    assert useful_memory.id not in {memory.id for memory in store.list_memories()}
    assert store.clear_scope("user") >= 1
    assert all(memory.candidate.scope != "user" for memory in store.list_memories())


def test_memory_store_can_disable_user_memory_writes(tmp_path: Path) -> None:
    response = _response()
    store = JsonHermesMemoryStore(tmp_path / "memory.json")
    store.set_user_memory_enabled(False, clear_existing=True)

    stored = FeedbackProcessor(store).process(response, FeedbackEvent(hook="useful"))

    assert store.user_memory_enabled() is False
    assert stored
    assert all(memory.candidate.scope != "user" for memory in stored)
    assert all(memory.candidate.scope != "user" for memory in store.list_memories())


def test_feedback_memory_demo_writes_only_requested_path(tmp_path: Path) -> None:
    memory_path = tmp_path / "demo-memory.json"

    result = run_feedback_memory_demo(
        "我两周后考通信原理，基础一般，想找速成资料和真题解析。",
        hook="useful",
        note="计划有帮助",
        memory_path=memory_path,
    )

    assert memory_path.exists()
    assert result["feedback"]["hook"] == "useful"
    assert result["storedMemories"]


def test_feedback_memory_demo_can_disable_user_memory(tmp_path: Path) -> None:
    memory_path = tmp_path / "demo-memory.json"

    result = run_feedback_memory_demo(
        "我两周后考通信原理，基础一般，想找速成资料和真题解析。",
        hook="useful",
        note="计划有帮助",
        memory_path=memory_path,
        user_memory_enabled=False,
    )

    assert result["preferences"]["userMemoryEnabled"] is False
    assert result["storedMemories"]
    assert all(memory["candidate"]["scope"] != "user" for memory in result["storedMemories"])
