from __future__ import annotations

import pytest

from studyhub_rag.evaluation import collapse_to_materials, evaluate_case, evaluate_method
from studyhub_rag.schemas import QueryCase, SearchHit


def test_chunk_hits_are_collapsed_before_material_metrics() -> None:
    hits = [
        SearchHit("1:a", 1, 3.0, 1),
        SearchHit("1:b", 1, 2.0, 2),
        SearchHit("2:a", 2, 1.0, 3),
    ]
    collapsed = collapse_to_materials(hits, top_k=10)
    assert [hit.material_id for hit in collapsed] == [1, 2]
    assert [hit.rank for hit in collapsed] == [1, 2]


def test_graded_metrics() -> None:
    case = QueryCase("q", "query", "semantic", {2: 2, 1: 1})
    hits = [SearchHit("1", 1, 1.0, 1), SearchHit("2", 2, 0.9, 2)]
    metrics = evaluate_case(case, hits, top_k=2)
    assert metrics["recall_at_k"] == 1.0
    assert metrics["mrr"] == 1.0
    assert 0 < metrics["ndcg_at_k"] < 1.0


def test_permission_leak_is_a_hard_metric() -> None:
    cases = [QueryCase("q", "query", "exact", {1: 2})]
    summary, _ = evaluate_method(
        cases,
        {"q": [SearchHit("2", 2, 1.0, 1), SearchHit("1", 1, 0.5, 2)]},
        top_k=10,
        latency_ms=1.0,
        allowed_material_ids={1},
    )
    assert summary["permission_leak_count"] == 1
    assert summary["mrr"] == pytest.approx(0.5)
