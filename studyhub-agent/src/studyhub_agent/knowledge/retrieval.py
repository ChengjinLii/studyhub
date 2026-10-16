from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence

from studyhub_agent.contracts.knowledge import Chunk, Corpus, Evidence, KnowledgeScope, SearchHit, SearchResult
from studyhub_agent.contracts.wiki import WikiSnapshot
from studyhub_agent.knowledge.chunking import materialize_parents
from studyhub_agent.knowledge.providers import Embedder, KnowledgeBackendError, Reranker, vectors
from studyhub_agent.knowledge.wiki import WikiIndex


def _tokens(text: str) -> list[str]:
    result = re.findall(r"[a-z0-9_]+", text.casefold())
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        result.extend(run)
        result.extend(run[index : index + 2] for index in range(len(run) - 1))
    return result


class _KeywordIndex:
    def __init__(self, chunks: Sequence[Chunk]) -> None:
        self.chunks = tuple(chunks)
        self.frequencies = tuple(Counter(_tokens(row.context_header + "\n" + row.text)) for row in chunks)
        document_frequency: Counter[str] = Counter()
        for frequency in self.frequencies:
            document_frequency.update(frequency.keys())
        self.idf = {
            term: math.log(1 + (len(chunks) - count + 0.5) / (count + 0.5))
            for term, count in document_frequency.items()
        }
        self.lengths = tuple(sum(row.values()) for row in self.frequencies)
        self.average = sum(self.lengths) / max(1, len(self.lengths))

    def search(self, query: str) -> list[tuple[str, float]]:
        terms = set(_tokens(query))
        scores: list[tuple[str, float]] = []
        for chunk, frequency, length in zip(self.chunks, self.frequencies, self.lengths, strict=True):
            score = 0.0
            for term in terms:
                count = frequency.get(term, 0)
                if count:
                    denominator = count + 1.5 * (0.25 + 0.75 * length / max(self.average, 1))
                    score += self.idf[term] * count * 2.5 / denominator
            if score > 0:
                scores.append((chunk.chunk_id, score))
        return sorted(scores, key=lambda row: (-row[1], row[0]))


def reciprocal_rank_fusion(rankings: Sequence[Sequence[str]], *, k: int = 60) -> list[tuple[str, float]]:
    if type(k) is not int or k < 1:
        raise ValueError("RRF k must be a positive integer")
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, key in enumerate(dict.fromkeys(ranking), start=1):
            scores[key] = scores.get(key, 0) + 1 / (k + rank)
    return sorted(scores.items(), key=lambda row: (-row[1], row[0]))


class KnowledgeRetriever:
    def __init__(
        self,
        corpus: Corpus,
        scope: KnowledgeScope,
        *,
        embedder: Embedder | None = None,
        reranker: Reranker | None = None,
        wiki: WikiSnapshot | None = None,
    ) -> None:
        self.corpus, self.scope = corpus, scope
        self.documents = {row.document_id: row for row in corpus.documents if scope.allows(row)}
        self.chunks = {row.chunk_id: row for row in corpus.chunks if row.document_id in self.documents}
        self.fingerprint = corpus.fingerprint
        self._keyword_index = _KeywordIndex(tuple(self.chunks.values()))
        self.embedder, self.reranker = embedder, reranker
        self._vectors: dict[str, tuple[float, ...]] = {}
        self.parents = {
            parent.parent_id: parent
            for document in self.documents.values()
            for parent in materialize_parents(
                document, tuple(row for row in self.chunks.values() if row.document_id == document.document_id)
            )
        }
        self._parent_children: dict[str, list[Chunk]] = {}
        for row in self.chunks.values():
            self._parent_children.setdefault(row.parent_id, []).append(row)
        for rows in self._parent_children.values():
            rows.sort(key=lambda row: row.ordinal)
        self.wiki = WikiIndex(corpus, scope, wiki) if wiki is not None else None

    @property
    def configuration(self) -> dict:
        return {
            "corpus_fingerprint": self.fingerprint,
            "knowledge_base_ids": sorted(self.scope.knowledge_base_ids),
            "document_ids": sorted(self.scope.document_ids) if self.scope.document_ids is not None else None,
            "embedding": self.embedder.identity if self.embedder else None,
            "reranker": self.reranker.identity if self.reranker else None,
            "fusion": "rrf@1:k=60:recall=50",
            "parent_context": "scoped-whole-parent-v1",
            "wiki": self.wiki.snapshot.extractor if self.wiki else None,
        }

    def evidence(self, chunk: Chunk) -> Evidence:
        if chunk.chunk_id not in self.chunks:
            raise ValueError("source is outside the knowledge scope")
        document = self.documents[chunk.document_id]
        return Evidence(
            **{
                key: getattr(chunk, key)
                for key in (
                    "chunk_id",
                    "document_id",
                    "revision",
                    "context_header",
                    "text",
                    "start",
                    "end",
                    "line_start",
                    "line_end",
                    "parent_id",
                    "page_start",
                    "page_end",
                )
            },
            knowledge_base_id=document.knowledge_base_id,
            title=document.title,
        )

    def search(self, query: str, *, mode: str = "hybrid", limit: int = 5, max_chars: int = 12000) -> SearchResult:
        if mode not in {"keyword", "semantic", "hybrid"}:
            raise ValueError("mode must be keyword, semantic or hybrid")
        if not query.strip() or len(query) > 2000:
            raise ValueError("query must contain 1-2000 characters")
        if type(limit) is not int or not 1 <= limit <= 30 or not 256 <= max_chars <= 48000:
            raise ValueError("invalid search output budget")
        effective, notices = mode, []
        if mode == "semantic" and self.embedder is None:
            raise KnowledgeBackendError("semantic search requires an embedding provider")
        if mode == "hybrid" and self.embedder is None:
            effective = "keyword"
            notices.append("embedding_not_configured:keyword_only")
        chunks = list(self.chunks.values())
        keyword = self._keyword_index.search(query)[:50] if effective != "semantic" else []
        semantic = self._semantic(query, chunks)[:50] if effective != "keyword" and chunks else []
        channels: dict[str, list[str]] = {}
        wiki = [(key, 1.0) for key in self.wiki.recall(query)[:50]] if self.wiki else []
        for name, ranking in (("keyword", keyword), ("semantic", semantic), ("wiki", wiki)):
            for key, _ in ranking:
                channels.setdefault(key, []).append(name)
        ranking = (
            reciprocal_rank_fusion([[key for key, _ in rows] for rows in (keyword, semantic, wiki)])
            if effective == "hybrid" or wiki
            else keyword
            if effective == "keyword"
            else semantic
        )
        if self.reranker and ranking:
            candidates = ranking[:50]
            passages = [self.chunks[key].context_header + "\n" + self.chunks[key].text for key, _ in candidates]
            scores = list(self.reranker.score(query, passages))
            if len(scores) != len(candidates) or any(not math.isfinite(score) for score in scores):
                raise KnowledgeBackendError("reranker returned invalid scores")
            ranking = sorted(
                [(key, score) for (key, _), score in zip(candidates, scores, strict=True)],
                key=lambda row: (-row[1], row[0]),
            )
        hits, used, seen_parents = [], 0, set()
        for key, score in ranking:
            chunk = self.chunks[key]
            if chunk.parent_id in seen_parents:
                continue
            parent_children = self._parent_children[chunk.parent_id]
            size = sum(len(row.text) + len(row.context_header) + 256 for row in parent_children)
            if used + size > max_chars:
                notices.append("evidence_omitted:output_budget")
                continue
            hits.append(
                SearchHit(
                    evidence=self.evidence(chunk),
                    score=score,
                    channels=tuple(channels[key]),
                    context=tuple(self.evidence(row) for row in parent_children if row.chunk_id != key),
                )
            )
            seen_parents.add(chunk.parent_id)
            used += size
            if len(hits) == limit:
                break
        return SearchResult(
            query=query,
            requested_mode=mode,
            effective_mode=effective,
            hits=tuple(hits),
            notices=tuple(dict.fromkeys(notices)),
        )

    def _semantic(self, query: str, chunks: Sequence[Chunk]) -> list[tuple[str, float]]:
        assert self.embedder is not None
        missing = [row for row in chunks if row.chunk_id not in self._vectors]
        for index in range(0, len(missing), 32):
            batch = missing[index : index + 32]
            rows = vectors(self.embedder.embed([row.context_header + "\n" + row.text for row in batch]), len(batch))
            self._vectors.update((chunk.chunk_id, row) for chunk, row in zip(batch, rows, strict=True))
        query_vector = vectors(self.embedder.embed([query]), 1)[0]
        scores = []
        for chunk in chunks:
            vector = self._vectors[chunk.chunk_id]
            if len(vector) != len(query_vector):
                raise KnowledgeBackendError("query and document embedding dimensions differ")
            score = sum(a * b for a, b in zip(vector, query_vector, strict=True))
            score /= math.hypot(*vector) * math.hypot(*query_vector)
            if not math.isfinite(score):
                raise KnowledgeBackendError("invalid semantic similarity")
            scores.append((chunk.chunk_id, score))
        return sorted(scores, key=lambda row: (-row[1], row[0]))

    def read(
        self, source_id: str, *, offset: int = 0, limit: int = 5, context: int = 0, query: str | None = None
    ) -> tuple[Evidence, ...]:
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError("invalid reading window")
        if type(context) is not int or not 0 <= context <= 5:
            raise ValueError("context must be between 0 and 5")
        if query is not None:
            if not isinstance(query, str) or not query.strip() or len(query) > 200:
                raise ValueError("invalid document query")
            if source_id in self.documents:
                document_id = source_id
            elif source_id in self.chunks:
                document_id = self.chunks[source_id].document_id
            elif source_id in self.parents:
                document_id = self.parents[source_id].document_id
            else:
                raise ValueError("source_not_found")
            terms = [term.casefold() for term in query.split()]
            rows = sorted(
                (row for row in self.chunks.values() if row.document_id == document_id),
                key=lambda row: row.ordinal,
            )
            matches = [
                row for row in rows
                if all(term in (row.context_header + " " + row.text).casefold() for term in terms)
            ]
            selected = matches[offset : offset + limit]
        elif source_id in self.chunks:
            chunk = self.chunks[source_id]
            rows = [row for row in self.chunks.values() if row.document_id == chunk.document_id]
            rows.sort(key=lambda row: row.ordinal)
            position = next(index for index, row in enumerate(rows) if row.chunk_id == source_id)
            selected = rows[max(0, position - context) : position + context + 1]
        elif source_id in self.parents:
            selected = self._parent_children[source_id]
        elif source_id in self.documents:
            rows = sorted(
                (row for row in self.chunks.values() if row.document_id == source_id), key=lambda row: row.ordinal
            )
            selected = rows[offset : offset + limit]
        else:
            raise ValueError("source_not_found")
        if sum(len(row.text) + len(row.context_header) + 256 for row in selected) > 16000:
            raise ValueError("reading window exceeds output budget; reduce limit or context")
        return tuple(self.evidence(row) for row in selected)
