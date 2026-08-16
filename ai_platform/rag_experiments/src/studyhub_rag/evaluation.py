from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from studyhub_rag.schemas import QueryCase, SearchHit


def collapse_to_materials(hits: Sequence[SearchHit], *, top_k: int) -> list[SearchHit]:
    seen: set[int] = set()
    result: list[SearchHit] = []
    for hit in hits:
        if hit.material_id in seen:
            continue
        seen.add(hit.material_id)
        result.append(hit.with_rank(len(result) + 1))
        if len(result) >= top_k:
            break
    return result


def _dcg(grades: Sequence[int]) -> float:
    return sum((2**grade - 1) / math.log2(rank + 1) for rank, grade in enumerate(grades, start=1))


def evaluate_case(case: QueryCase, hits: Sequence[SearchHit], *, top_k: int) -> dict[str, float]:
    ranked = collapse_to_materials(hits, top_k=top_k)
    relevant = {material_id for material_id, grade in case.relevance.items() if grade > 0}
    if not relevant:
        return {"hit_at_k": 0.0, "recall_at_k": 0.0, "mrr": 0.0, "ndcg_at_k": 0.0, "map_at_k": 0.0}
    retrieved = [hit.material_id for hit in ranked]
    binary = [1 if material_id in relevant else 0 for material_id in retrieved]
    hit_at_k = float(any(binary))
    recall_at_k = sum(binary) / len(relevant)
    first = next((rank for rank, value in enumerate(binary, start=1) if value), None)
    mrr = 1.0 / first if first else 0.0
    precisions = [sum(binary[:rank]) / rank for rank, value in enumerate(binary, start=1) if value]
    map_at_k = sum(precisions) / min(len(relevant), top_k)
    grades = [case.relevance.get(material_id, 0) for material_id in retrieved]
    ideal = sorted(case.relevance.values(), reverse=True)[:top_k]
    ideal_dcg = _dcg(ideal)
    ndcg = _dcg(grades) / ideal_dcg if ideal_dcg else 0.0
    return {
        "hit_at_k": hit_at_k,
        "recall_at_k": recall_at_k,
        "mrr": mrr,
        "ndcg_at_k": ndcg,
        "map_at_k": map_at_k,
    }


def evaluate_method(
    cases: Sequence[QueryCase],
    rankings: Mapping[str, Sequence[SearchHit]],
    *,
    top_k: int,
    latency_ms: float,
    allowed_material_ids: set[int],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    per_query: list[dict[str, Any]] = []
    top_scores: dict[str, float] = {}
    leaked: set[int] = set()
    for case in cases:
        hits = list(rankings.get(case.query_id, []))
        leaked.update(hit.material_id for hit in hits if hit.material_id not in allowed_material_ids)
        top_scores[case.query_id] = hits[0].score if hits else float("-inf")
        metrics = evaluate_case(case, hits, top_k=top_k)
        per_query.append(
            {
                "query_id": case.query_id,
                "query": case.query,
                "query_type": case.query_type,
                "answerable": case.answerable,
                **metrics,
                "top_material_ids": [hit.material_id for hit in collapse_to_materials(hits, top_k=top_k)],
            }
        )
    answerable_rows = [row for row in per_query if row["answerable"]]
    answerable_scores = [
        top_scores[row["query_id"]] for row in answerable_rows if np.isfinite(top_scores[row["query_id"]])
    ]
    threshold = float(np.quantile(answerable_scores, 0.05)) if answerable_scores else float("inf")
    no_answer_rows = [row for row in per_query if not row["answerable"]]
    no_answer_fpr = (
        sum(top_scores[row["query_id"]] >= threshold for row in no_answer_rows) / len(no_answer_rows)
        if no_answer_rows
        else 0.0
    )
    summary: dict[str, Any] = {
        "queries": len(cases),
        "answerable_queries": len(answerable_rows),
        "no_answer_queries": len(no_answer_rows),
        "latency_ms": float(latency_ms),
        "no_answer_threshold_p05": threshold,
        "no_answer_fpr": float(no_answer_fpr),
        "permission_leak_count": len(leaked),
        "permission_leaked_ids": sorted(leaked),
    }
    for name in ("hit_at_k", "recall_at_k", "mrr", "ndcg_at_k", "map_at_k"):
        summary[name] = float(np.mean([row[name] for row in answerable_rows])) if answerable_rows else 0.0
    by_type: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in answerable_rows:
        by_type[str(row["query_type"])].append(row)
    summary["by_query_type"] = {
        query_type: {name: float(np.mean([row[name] for row in rows])) for name in ("recall_at_k", "mrr", "ndcg_at_k")}
        for query_type, rows in sorted(by_type.items())
    }
    return summary, per_query
