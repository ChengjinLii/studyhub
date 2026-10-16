import math

import pytest

from studyhub_agent.contracts.knowledge import Corpus, KnowledgeScope
from studyhub_agent.knowledge.chunking import make_document
from studyhub_agent.knowledge.providers import KnowledgeBackendError
from studyhub_agent.knowledge.retrieval import KnowledgeRetriever, reciprocal_rank_fusion
from studyhub_agent.knowledge.store import upsert_document


class Embedding:
    identity = "test-embedding@1"

    def __init__(self):
        self.seen = []

    def embed(self, texts):
        self.seen.extend(texts)
        return [[1, 0] if "投影" in text or "几何方向" in text else [0, 1] for text in texts]


def test_keyword_searches_body_and_reports_hybrid_fallback(retriever):
    result = retriever.search("QR 分解")
    assert result.effective_mode == "keyword"
    assert result.notices == ("embedding_not_configured:keyword_only",)
    assert "最小二乘" in result.hits[0].evidence.text
    assert result.hits[0].channels == ("keyword",)
    assert not retriever.search("zzzzzz").hits


def test_hybrid_fuses_independent_retrieval_paths(corpus):
    embedding = Embedding()
    retriever = KnowledgeRetriever(corpus, KnowledgeScope(knowledge_base_ids=frozenset({"demo"})), embedder=embedding)
    result = retriever.search("几何方向")
    assert result.effective_mode == "hybrid"
    assert "投影" in result.hits[0].evidence.text
    assert not result.notices
    retriever.search("投影")
    assert len([text for text in embedding.seen if text.startswith("正交投影\n")]) == 1
    assert not any("991" in text for text in embedding.seen)
    assert retriever.configuration["embedding"] == "test-embedding@1"


def test_scope_filters_before_ranking_and_context_expansion(corpus):
    public = next(row for row in corpus.documents if row.source == "projection.md")
    scope = KnowledgeScope(
        knowledge_base_ids=frozenset({"demo", "private"}), document_ids=frozenset({public.document_id})
    )
    retriever = KnowledgeRetriever(corpus, scope)
    assert not retriever.search("991", mode="keyword").hits
    hidden = next(row for row in corpus.chunks if "991" in row.text)
    with pytest.raises(ValueError, match="source_not_found"):
        retriever.read(hidden.chunk_id, context=5)
    empty = KnowledgeRetriever(corpus, KnowledgeScope(knowledge_base_ids=frozenset()))
    assert not empty.search("正交").hits


def test_reading_returns_each_neighbour_with_its_own_evidence():
    document = make_document("demo", "notes", "# 标题\n" + "每段内容都有独立的来源。\n" * 50)
    corpus = upsert_document(Corpus(), document, child_size=64, parent_size=200)
    retriever = KnowledgeRetriever(corpus, KnowledgeScope(knowledge_base_ids=frozenset({"demo"})))
    focus = corpus.chunks[2]
    evidence = retriever.read(focus.chunk_id, context=1)
    assert len(evidence) == 3
    assert len({row.citation for row in evidence}) == 3
    assert all(document.text[row.start : row.end] == row.text for row in evidence)
    assert retriever.read(document.document_id, offset=1, limit=2) == evidence[:2]


def test_rrf_uses_rank_not_raw_score_and_deduplicates():
    result = reciprocal_rank_fusion([["a", "a", "b"], ["b", "c"]], k=1)
    assert result[0] == ("b", 1 / 3 + 1 / 2)
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([], k=0)


def test_unavailable_embedding_is_not_silently_semantic(retriever):
    with pytest.raises(KnowledgeBackendError, match="requires"):
        retriever.search("test", mode="semantic")


def test_provider_failure_is_not_empty_or_keyword_fallback(corpus):
    class Broken(Embedding):
        def embed(self, texts):
            raise KnowledgeBackendError("offline")

    retriever = KnowledgeRetriever(corpus, KnowledgeScope(knowledge_base_ids=frozenset({"demo"})), embedder=Broken())
    with pytest.raises(KnowledgeBackendError, match="offline"):
        retriever.search("投影")


@pytest.mark.parametrize("vector", [[], [0, 0], [math.nan, 1], [math.inf, 0]])
def test_invalid_embedding_vectors_fail(corpus, vector):
    class Bad(Embedding):
        def embed(self, texts):
            return [vector for _ in texts]

    retriever = KnowledgeRetriever(corpus, KnowledgeScope(knowledge_base_ids=frozenset({"demo"})), embedder=Bad())
    with pytest.raises(KnowledgeBackendError):
        retriever.search("投影")


def test_reranker_preserves_formula_and_code_and_reorders(corpus):
    class Ranking:
        identity = "test-reranker@1"

        def score(self, query, passages):
            assert any("v^T u / u^T u" in text for text in passages)
            return [1 if "QR" in text else 0 for text in passages]

    retriever = KnowledgeRetriever(corpus, KnowledgeScope(knowledge_base_ids=frozenset({"demo"})), reranker=Ranking())
    assert "QR" in retriever.search("正交").hits[0].evidence.text


def test_output_budget_omits_whole_evidence_instead_of_changing_its_body(retriever):
    result = retriever.search("正交", max_chars=256)
    assert not result.hits
    assert "evidence_omitted:output_budget" in result.notices


@pytest.mark.parametrize("kwargs", [{"mode": "bad"}, {"limit": True}, {"limit": 0}, {"max_chars": 1}])
def test_invalid_search_parameters(retriever, kwargs):
    with pytest.raises(ValueError):
        retriever.search("query", **kwargs)


def test_read_document_query_stays_within_document_and_rejects_bad_input(retriever):
    document = next(row for row in retriever.documents.values() if row.source == "least-squares.md")
    found = retriever.read(document.document_id, query="QR 分解")
    assert found and all("QR" in item.text for item in found)
    assert not retriever.read(document.document_id, query="missing-token")
    chunk = next(row for row in retriever.chunks.values() if row.document_id == document.document_id)
    assert retriever.read(chunk.chunk_id, query="QR")
    with pytest.raises(ValueError, match="invalid document query"):
        retriever.read(document.document_id, query="   ")
    with pytest.raises(ValueError, match="source_not_found"):
        retriever.read("d_hidden", query="991")
