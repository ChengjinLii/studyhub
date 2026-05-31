from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Any

from ai_platform.serving.embedding_provider import EmbeddingProvider, get_mock_embedding_provider
from ai_platform.shared.mock_embedding import cosine_similarity, expand_tokens, tokenize


@dataclass(frozen=True)
class SearchDocument:
    id: str
    type: str
    title: str
    text: str
    metadata: dict[str, Any]

    @property
    def searchable_text(self) -> str:
        metadata_text = " ".join(str(value) for value in self.metadata.values() if value)
        return f"{self.title}\n{self.text}\n{metadata_text}"


@dataclass(frozen=True)
class SearchResult:
    document: SearchDocument
    score: float
    dense_score: float
    sparse_score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.document.id,
            "type": self.document.type,
            "title": self.document.title,
            "score": round(self.score, 4),
            "denseScore": round(self.dense_score, 4),
            "sparseScore": round(self.sparse_score, 4),
            "metadata": self.document.metadata,
        }


@dataclass(frozen=True)
class RankedHit:
    index: int
    score: float


class DenseVectorIndex:
    """Small in-memory kNN index with a FAISS-like add/search shape."""

    def __init__(self, vectors: list[list[float]]) -> None:
        self.vectors = vectors

    def search(self, query_vector: list[float], *, top_k: int, candidate_indices: set[int] | None = None) -> list[RankedHit]:
        hits: list[RankedHit] = []
        for index, vector in enumerate(self.vectors):
            if candidate_indices is not None and index not in candidate_indices:
                continue
            hits.append(RankedHit(index=index, score=cosine_similarity(query_vector, vector)))
        hits.sort(key=lambda item: item.score, reverse=True)
        return hits[: max(1, top_k)]


class BM25Index:
    """Sparse lexical index used for hybrid retrieval."""

    def __init__(self, documents: list[SearchDocument], *, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._term_frequencies = [Counter(_lexical_tokens(document.searchable_text)) for document in documents]
        self._doc_lengths = [sum(counter.values()) for counter in self._term_frequencies]
        self._average_doc_length = sum(self._doc_lengths) / len(self._doc_lengths) if self._doc_lengths else 0.0
        document_frequencies: Counter[str] = Counter()
        for counter in self._term_frequencies:
            document_frequencies.update(counter.keys())
        doc_count = len(documents)
        self._idf = {
            term: math.log(1.0 + (doc_count - frequency + 0.5) / (frequency + 0.5))
            for term, frequency in document_frequencies.items()
        }

    def search(self, query: str, *, top_k: int, candidate_indices: set[int] | None = None) -> list[RankedHit]:
        query_terms = _lexical_tokens(query)
        hits: list[RankedHit] = []
        for index, frequencies in enumerate(self._term_frequencies):
            if candidate_indices is not None and index not in candidate_indices:
                continue
            score = self._score(query_terms, frequencies, self._doc_lengths[index])
            if score > 0:
                hits.append(RankedHit(index=index, score=score))
        hits.sort(key=lambda item: item.score, reverse=True)
        return hits[: max(1, top_k)]

    def _score(self, query_terms: list[str], frequencies: Counter[str], doc_length: int) -> float:
        if not query_terms or not frequencies or not self._average_doc_length:
            return 0.0
        score = 0.0
        for term in query_terms:
            term_frequency = frequencies.get(term, 0)
            if term_frequency == 0:
                continue
            idf = self._idf.get(term, 0.0)
            denominator = term_frequency + self.k1 * (1.0 - self.b + self.b * doc_length / self._average_doc_length)
            score += idf * (term_frequency * (self.k1 + 1.0)) / denominator
        return score


class InMemorySemanticSearch:
    def __init__(self, documents: list[SearchDocument], embedding_provider: EmbeddingProvider | None = None) -> None:
        self.embedding_provider = embedding_provider or get_mock_embedding_provider()
        self.documents = documents
        self._document_vectors = self.embedding_provider.embed_documents([document.searchable_text for document in documents])
        self._dense_index = DenseVectorIndex(self._document_vectors)
        self._sparse_index = BM25Index(documents)

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        type_filter: str | None = None,
        mode: str = "hybrid",
        rrf_k: int = 60,
    ) -> list[SearchResult]:
        candidate_indices = self._candidate_indices(type_filter)
        dense_hits = self._dense_index.search(
            self.embedding_provider.embed_query(query),
            top_k=max(top_k * 4, 10),
            candidate_indices=candidate_indices,
        )
        sparse_hits = self._sparse_index.search(query, top_k=max(top_k * 4, 10), candidate_indices=candidate_indices)

        if mode == "dense":
            fused_scores = {hit.index: hit.score for hit in dense_hits}
        elif mode == "sparse":
            fused_scores = {hit.index: hit.score for hit in sparse_hits}
        elif mode == "hybrid":
            fused_scores = reciprocal_rank_fusion([dense_hits, sparse_hits], k=rrf_k)
        else:
            raise ValueError("mode must be one of: dense, sparse, hybrid")

        dense_scores = {hit.index: hit.score for hit in dense_hits}
        sparse_scores = {hit.index: hit.score for hit in sparse_hits}
        results = [
            SearchResult(
                document=self.documents[index],
                score=score,
                dense_score=dense_scores.get(index, 0.0),
                sparse_score=sparse_scores.get(index, 0.0),
            )
            for index, score in fused_scores.items()
        ]
        results.sort(key=lambda item: item.score, reverse=True)
        return results[: max(1, top_k)]

    def _candidate_indices(self, type_filter: str | None) -> set[int] | None:
        if not type_filter:
            return None
        return {index for index, document in enumerate(self.documents) if document.type == type_filter}


def reciprocal_rank_fusion(rankings: list[list[RankedHit]], *, k: int = 60) -> dict[int, float]:
    fused: dict[int, float] = {}
    for hits in rankings:
        for rank, hit in enumerate(hits, start=1):
            fused[hit.index] = fused.get(hit.index, 0.0) + 1.0 / (k + rank)
    return fused


def _lexical_tokens(text: str) -> list[str]:
    return expand_tokens(tokenize(text))
