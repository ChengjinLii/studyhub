from __future__ import annotations

from pathlib import Path
import sys


AI_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AI_PLATFORM_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_platform.scripts.semantic_search_demo import DEFAULT_SAMPLE_PATH, load_documents
from ai_platform.retrieval.semantic_search import InMemorySemanticSearch


def test_semantic_search_returns_relevant_materials_for_natural_query() -> None:
    searcher = InMemorySemanticSearch(load_documents(DEFAULT_SAMPLE_PATH))

    results = searcher.search("通原考试资料和复习重点", top_k=3, mode="hybrid")

    assert results
    assert results[0].document.id in {"material-001", "request-001", "column-001"}
    assert any(result.document.id == "material-001" for result in results)
    assert results[0].dense_score > 0
    assert results[0].sparse_score > 0


def test_semantic_search_type_filter_limits_results() -> None:
    searcher = InMemorySemanticSearch(load_documents(DEFAULT_SAMPLE_PATH))

    results = searcher.search("数据结构实验报告", top_k=5, type_filter="request", mode="hybrid")

    assert results
    assert all(result.document.type == "request" for result in results)
    assert results[0].document.id == "request-002"


def test_semantic_search_supports_dense_and_sparse_modes() -> None:
    searcher = InMemorySemanticSearch(load_documents(DEFAULT_SAMPLE_PATH))

    dense_results = searcher.search("高数微积分考点", top_k=2, mode="dense")
    sparse_results = searcher.search("高数微积分考点", top_k=2, mode="sparse")

    assert dense_results
    assert sparse_results
    assert dense_results[0].score == dense_results[0].dense_score
    assert sparse_results[0].score == sparse_results[0].sparse_score
