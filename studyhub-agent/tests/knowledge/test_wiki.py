import json

import httpx
import pytest

from studyhub_agent.cli import main
from studyhub_agent.contracts.knowledge import Corpus, KnowledgeScope
from studyhub_agent.contracts.wiki import WikiFact
from studyhub_agent.knowledge.chunking import make_document
from studyhub_agent.knowledge.providers import KnowledgeBackendError
from studyhub_agent.knowledge.retrieval import KnowledgeRetriever
from studyhub_agent.knowledge.store import delete_document, load_corpus, upsert_document
from studyhub_agent.knowledge.wiki import (
    HeadingExtractor,
    HttpWikiExtractor,
    WikiIndex,
    load_wiki,
    save_wiki,
    update_wiki,
)

SCOPE = KnowledgeScope(knowledge_base_ids=frozenset({"demo"}))


class Extractor:
    identity = "test-extractor@1"

    def __init__(self):
        self.calls = []

    def extract(self, evidence):
        self.calls.append(evidence.chunk_id)
        return [
            WikiFact(
                kind="concept",
                name="Projection",
                aliases=("orthogonal projection",),
                claim=evidence.text.strip(),
                quote=evidence.text.strip(),
            )
        ]


def sample():
    corpus = upsert_document(Corpus(), make_document("demo", "one", "Residual is orthogonal."))
    return upsert_document(corpus, make_document("demo", "two", "Projection minimizes error."))


def test_map_reduce_combines_documents_with_chunk_revision_and_quote_provenance():
    corpus, extractor = sample(), Extractor()
    result = update_wiki(corpus, SCOPE, extractor)
    assert result.mapped_chunks == 2 and len(result.snapshot.pages) == 1
    page = result.snapshot.pages[0]
    assert len(page.claims) == 2
    assert len({source.document_id for claim in page.claims for source in claim.sources}) == 2
    assert all(f"[{source.chunk_id}]" in page.body for claim in page.claims for source in claim.sources)


def test_unchanged_chunks_are_not_sent_to_model_again(tmp_path):
    corpus, extractor = sample(), Extractor()
    first = update_wiki(corpus, SCOPE, extractor)
    path = tmp_path / "wiki.json"
    save_wiki(path, first.snapshot)
    second = update_wiki(corpus, SCOPE, extractor, load_wiki(path))
    assert second.mapped_chunks == 0 and second.reused_chunks == 2
    assert not second.updated_pages and not second.deleted_pages
    assert len(extractor.calls) == 2


def test_revision_update_and_deletion_retract_old_claims():
    corpus, extractor = sample(), Extractor()
    first = update_wiki(corpus, SCOPE, extractor)
    original = next(row for row in corpus.documents if row.source == "one")
    changed = upsert_document(corpus, make_document("demo", "one", "New projection explanation."))
    second = update_wiki(changed, SCOPE, extractor, first.snapshot)
    assert second.mapped_chunks == second.reused_chunks == 1
    assert "Residual is orthogonal" not in second.snapshot.pages[0].body
    removed = delete_document(changed, original.document_id)
    third = update_wiki(removed, SCOPE, extractor, second.snapshot)
    assert "New projection" not in third.snapshot.pages[0].body
    empty = update_wiki(Corpus(), SCOPE, extractor, third.snapshot)
    assert empty.snapshot.pages == () and empty.deleted_pages


def test_model_identity_change_invalidates_map_cache():
    corpus, extractor = sample(), Extractor()
    first = update_wiki(corpus, SCOPE, extractor)
    extractor.identity = "test-extractor@2"
    second = update_wiki(corpus, SCOPE, extractor, first.snapshot)
    assert second.mapped_chunks == 2 and second.reused_chunks == 0


def test_updating_another_scope_does_not_silently_overwrite_existing_wiki():
    corpus, extractor = sample(), Extractor()
    first = update_wiki(corpus, SCOPE, extractor)
    with pytest.raises(ValueError, match="scope differs"):
        update_wiki(
            corpus,
            KnowledgeScope(knowledge_base_ids=frozenset({"another"})),
            extractor,
            first.snapshot,
        )


def test_nonexistent_quote_fails_before_snapshot_publish(tmp_path):
    corpus, extractor = sample(), Extractor()
    first = update_wiki(corpus, SCOPE, extractor)
    path = tmp_path / "wiki.json"
    save_wiki(path, first.snapshot)
    before = path.read_bytes()

    class Bad(Extractor):
        identity = "invalid@2"

        def extract(self, evidence):
            return [WikiFact(kind="concept", name="Invented", claim="Invented", quote="Not in source")]

    with pytest.raises(KnowledgeBackendError, match="stale source"):
        update_wiki(corpus, SCOPE, Bad(), first.snapshot)
    assert path.read_bytes() == before


def test_document_scope_is_applied_before_wiki_search_and_retrieval():
    corpus, extractor = sample(), Extractor()
    snapshot = update_wiki(corpus, SCOPE, extractor).snapshot
    allowed = next(row for row in corpus.documents if row.source == "one")
    scope = KnowledgeScope(knowledge_base_ids=frozenset({"demo"}), document_ids=frozenset({allowed.document_id}))
    index = WikiIndex(corpus, scope, snapshot)
    assert len(index.pages[0].claims) == 1
    assert "minimizes error" not in index.pages[0].body
    retriever = KnowledgeRetriever(corpus, scope, wiki=snapshot)
    result = retriever.search("orthogonal projection")
    assert result.hits and "wiki" in result.hits[0].channels
    assert all(row.evidence.document_id == allowed.document_id for row in result.hits)


def test_stale_wiki_is_not_used_to_resurrect_deleted_sources():
    corpus = sample()
    snapshot = update_wiki(corpus, SCOPE, Extractor()).snapshot
    changed = delete_document(corpus, corpus.documents[0].document_id)
    with pytest.raises(ValueError, match="stale"):
        WikiIndex(changed, SCOPE, snapshot)


def test_explicit_aliases_merge_entities_but_kinds_and_knowledge_bases_stay_separate():
    corpus = sample()

    class Alias(Extractor):
        def extract(self, evidence):
            name = "Projection" if "Residual" in evidence.text else "orthogonal projection"
            return [
                WikiFact(kind=kind, name=name, aliases=("Projection",), claim=evidence.text, quote=evidence.text)
                for kind in ("entity", "concept")
            ]

    snapshot = update_wiki(corpus, SCOPE, Alias()).snapshot
    assert len(snapshot.pages) == 2
    assert {page.kind for page in snapshot.pages} == {"entity", "concept"}


@pytest.mark.parametrize(
    "response",
    [
        {"choices": []},
        {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]},
        {"choices": [{"finish_reason": "stop", "message": {"content": "not json"}}]},
    ],
)
def test_model_response_errors_are_sanitized(response):
    client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=response)))
    extractor = HttpWikiExtractor("http://model/v1/chat/completions", "model@version", client=client)
    from studyhub_agent.knowledge.wiki import _evidence

    corpus = sample()
    with client, pytest.raises(KnowledgeBackendError, match="invalid wiki extraction"):
        extractor.extract(_evidence(corpus, corpus.chunks[0].chunk_id))


def test_model_wire_contract_extracts_structured_facts():
    def respond(request):
        body = json.loads(request.content)
        source = json.loads(body["messages"][1]["content"])
        assert body["temperature"] == 0 and body["model"] == "model@revision"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "facts": [
                                        {
                                            "kind": "concept",
                                            "name": "Projection",
                                            "aliases": [],
                                            "claim": source["text"],
                                            "quote": source["text"],
                                        }
                                    ]
                                }
                            )
                        },
                    }
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        extractor = HttpWikiExtractor("http://model/v1/chat/completions", "model@revision", client=client)
        assert len(update_wiki(sample(), SCOPE, extractor).snapshot.pages) == 1


def test_cli_incremental_wiki_workflow_is_offline(tmp_path, capsys, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("extractive workflow must not create a model client")

    monkeypatch.setattr("studyhub_agent.cli.httpx.Client", no_network)
    source, corpus, wiki = tmp_path / "notes.md", tmp_path / "corpus.json", tmp_path / "wiki.json"
    source.write_text("# Projection\nResidual is orthogonal.", encoding="utf-8")
    prefix = ["--corpus", str(corpus)]
    assert main([*prefix, "index", str(source)]) == 0
    capsys.readouterr()
    command = [*prefix, "wiki-build", "--extractive", "--output", str(wiki)]
    assert main(command) == 0
    assert json.loads(capsys.readouterr().out)["mapped_chunks"] == 1
    assert main(command) == 0
    assert json.loads(capsys.readouterr().out)["reused_chunks"] == 1
    assert main([*prefix, "--wiki", str(wiki), "wiki-search", "Projection"]) == 0
    assert len(json.loads(capsys.readouterr().out)["pages"]) == 1
    document_id = load_corpus(corpus).documents[0].document_id
    assert main([*prefix, "delete", document_id]) == 0
    capsys.readouterr()
    assert main(command) == 0
    assert json.loads(capsys.readouterr().out)["deleted_pages"]


def test_heading_baseline_is_explicitly_not_semantic_entity_extraction():
    result = update_wiki(sample(), SCOPE, HeadingExtractor())
    assert result.snapshot.pages == ()
