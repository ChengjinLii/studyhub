from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from studyhub_rag.schemas import SearchHit


def _hit_lookup(rankings: Sequence[Sequence[SearchHit]]) -> dict[str, SearchHit]:
    result: dict[str, SearchHit] = {}
    for ranking in rankings:
        for hit in ranking:
            result.setdefault(hit.chunk_id, hit)
    return result


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[SearchHit]], *, rrf_k: int = 60, top_k: int = 40
) -> list[SearchHit]:
    if rrf_k < 1:
        raise ValueError("rrf_k must be positive")
    scores: defaultdict[str, float] = defaultdict(float)
    for ranking in rankings:
        for hit in ranking:
            scores[hit.chunk_id] += 1.0 / (rrf_k + hit.rank)
    lookup = _hit_lookup(rankings)
    ordered = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))[:top_k]
    return [
        SearchHit(
            chunk_id=chunk_id,
            material_id=lookup[chunk_id].material_id,
            score=scores[chunk_id],
            rank=rank,
            title=lookup[chunk_id].title,
            text=lookup[chunk_id].text,
        )
        for rank, chunk_id in enumerate(ordered, start=1)
    ]


def weighted_score_fusion(
    rankings: Sequence[Sequence[SearchHit]], *, weights: Sequence[float], top_k: int = 40
) -> list[SearchHit]:
    if len(rankings) != len(weights):
        raise ValueError("Each ranking must have one weight")
    scores: defaultdict[str, float] = defaultdict(float)
    for ranking, weight in zip(rankings, weights, strict=True):
        if not ranking:
            continue
        values = [hit.score for hit in ranking]
        low, high = min(values), max(values)
        scale = high - low
        for hit in ranking:
            normalized = (hit.score - low) / scale if scale > 1e-12 else 1.0
            scores[hit.chunk_id] += float(weight) * normalized
    lookup = _hit_lookup(rankings)
    ordered = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))[:top_k]
    return [
        SearchHit(
            chunk_id=chunk_id,
            material_id=lookup[chunk_id].material_id,
            score=scores[chunk_id],
            rank=rank,
            title=lookup[chunk_id].title,
            text=lookup[chunk_id].text,
        )
        for rank, chunk_id in enumerate(ordered, start=1)
    ]
