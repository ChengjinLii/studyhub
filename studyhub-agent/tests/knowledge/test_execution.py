import pytest

from studyhub_agent.architectures.knowledge_verify import KnowledgeVerifyArchitecture
from studyhub_agent.contracts.episode import Budget, EpisodeSpec, KnowledgePrincipal, Termination, ToolCall
from studyhub_agent.contracts.knowledge import KnowledgeScope
from studyhub_agent.contracts.knowledge_citations import check_knowledge_citations
from studyhub_agent.contracts.knowledge_prompts import KNOWLEDGE_PROMPTS, KNOWLEDGE_SYSTEM_KEY
from studyhub_agent.contracts.wiki import WikiFact
from studyhub_agent.environments.knowledge import KnowledgeEnvironment
from studyhub_agent.knowledge.retrieval import KnowledgeRetriever
from studyhub_agent.knowledge.wiki import update_wiki
from studyhub_agent.runtime.rag import RagPipeline
from studyhub_agent.runtime.runner import EpisodeRunner
from tests.runtime.fakes import ScriptedPolicy, count_chars, final_turn, tool_turn


def spec(*, turns=6):
    return EpisodeSpec(
        episode_id="knowledge-test",
        task_id="question",
        user_message="如何计算正交投影？",
        principal=KnowledgePrincipal(principal_id="offline"),
        system_prompt=KNOWLEDGE_SYSTEM_KEY,
        tool_names=("search_knowledge", "read_document", "list_documents"),
        budget=Budget(max_turns=turns),
    )


def test_knowledge_identity_roundtrip_does_not_reintroduce_website_fields():
    original = spec()
    restored = EpisodeSpec.model_validate_json(original.model_dump_json())
    assert isinstance(restored.principal, KnowledgePrincipal)
    assert restored.model_dump() == original.model_dump()


def test_rag_uses_the_same_evidence_contract_as_agent(retriever):
    evidence = retriever.search("投影").hits[0].evidence
    policy = ScriptedPolicy([final_turn(f"分母要求向量非零。{evidence.citation}")])
    result = RagPipeline(retriever).run("投影", policy, count_tokens=lambda messages: 100)
    assert result.status == "answered"
    assert result.citations.ok
    assert result.evidence[0] == evidence
    assert evidence.chunk_id in policy.seen[0][-1].content


def test_empty_retrieval_does_not_call_model(retriever):
    policy = ScriptedPolicy([])
    result = RagPipeline(retriever).run("zzzzzz", policy, count_tokens=lambda messages: 1)
    assert result.status == "no_evidence"
    assert not policy.seen


def test_rag_withholds_uncited_or_fabricated_generation(retriever):
    for text in ("答案没有引用", "答案[k_old_revision]", ""):
        result = RagPipeline(retriever).run("投影", ScriptedPolicy([final_turn(text)]), count_tokens=lambda messages: 1)
        assert result.status in {"unverified", "invalid_generation"}
        assert result.answer is None


def test_rag_respects_real_prompt_budget(retriever):
    result = RagPipeline(retriever).run("投影", ScriptedPolicy([]), count_tokens=lambda messages: 100000)
    assert result.status == "context_budget"


def test_agent_search_read_and_citation_repair(retriever):
    evidence = retriever.search("投影").hits[0].evidence
    policy = ScriptedPolicy(
        [
            tool_turn(("search_knowledge", {"query": "投影"})),
            tool_turn(("read_document", {"id": evidence.chunk_id, "context": 1})),
            final_turn("错误引用[k_stale_revision]"),
            final_turn(f"向量不能为零。{evidence.citation}"),
        ]
    )
    runner = EpisodeRunner(prompts=KNOWLEDGE_PROMPTS, tokenizer_revision="test", count_tokens=count_chars)
    episode = runner.run(spec(), KnowledgeEnvironment(retriever), policy, architecture=KnowledgeVerifyArchitecture())
    assert episode.termination == Termination.FINAL_ANSWER
    assert episode.architecture_trace["citation_verified"]
    assert len(episode.architecture_trace["citation_checks"]) == 2
    assert episode.environment_trace["corpus_fingerprint"] == retriever.corpus.fingerprint
    assert len(episode.observations[-1].details["evidence_ids"]) == 1
    assert "购买" not in episode.messages[0].content.replace("不得要求登录网站、购买资料或调用网站业务接口。", "")


def test_invalid_citations_never_succeed_after_retry_budget(retriever):
    policy = ScriptedPolicy(
        [
            tool_turn(("search_knowledge", {"query": "投影"})),
            final_turn("没有引用"),
            final_turn("仍然没有引用"),
        ]
    )
    runner = EpisodeRunner(prompts=KNOWLEDGE_PROMPTS, tokenizer_revision="test", count_tokens=count_chars)
    episode = runner.run(
        spec(turns=3), KnowledgeEnvironment(retriever), policy, architecture=KnowledgeVerifyArchitecture()
    )
    assert episode.termination == Termination.MAX_TURNS
    assert episode.final_answer is None
    assert episode.architecture_trace["citation_verified"] is False


def test_metadata_is_not_source_evidence_and_reset_clears_exposure(retriever):
    environment = KnowledgeEnvironment(retriever)
    with pytest.raises(RuntimeError):
        environment.execute(ToolCall(call_id="1", name="list_documents", arguments={}))
    environment.reset(spec())
    listed = environment.execute(ToolCall(call_id="1", name="list_documents", arguments={}))
    assert listed.ok and not listed.details["evidence_ids"]
    assert all(row["knowledge_base_id"] == "demo" for row in listed.payload["documents"])
    environment.execute(ToolCall(call_id="2", name="search_knowledge", arguments={"query": "投影"}))
    assert environment.trace()["evidence_ids"]
    environment.reset(spec())
    assert not environment.trace()["evidence_ids"]


@pytest.mark.parametrize(
    "name,args",
    [
        ("search_knowledge", {"query": "投影", "knowledge_base_ids": ["private"]}),
        ("read_document", {"id": "k_hidden"}),
        ("read_document", {"id": "any", "context": True}),
        ("list_documents", {"limit": "10"}),
        ("unknown", {}),
    ],
)
def test_tool_arguments_cannot_widen_server_owned_scope(retriever, name, args):
    environment = KnowledgeEnvironment(retriever)
    environment.reset(spec())
    result = environment.execute(ToolCall(call_id="1", name=name, arguments=args))
    assert not result.ok
    assert not environment.trace()["evidence_ids"]


def test_citation_validation_rejects_old_versions(retriever):
    evidence = retriever.search("投影").hits[0].evidence
    assert check_knowledge_citations(evidence.citation, [evidence.chunk_id]).ok
    assert not check_knowledge_citations("[k_old_version]", [evidence.chunk_id]).ok
    assert not check_knowledge_citations("没有引用", [evidence.chunk_id]).ok
    assert check_knowledge_citations("找不到依据", []).ok


def test_wiki_agent_tools_are_hidden_without_a_wiki(retriever):
    env = KnowledgeEnvironment(retriever)
    assert {tool.name for tool in env.tool_specs()} == {
        "search_knowledge", "read_document", "list_documents"
    }
    env.reset(spec())
    denied = env.execute(ToolCall(call_id="w0", name="wiki_search", arguments={"query": "Projection"}))
    assert not denied.ok and not env.trace()["evidence_ids"]


def _wiki_retriever(corpus, scope):
    class Extractor:
        identity = "wiki-agent-test@1"

        def extract(self, evidence):
            return (WikiFact(
                kind="concept", name="Projection",
                claim=evidence.text.strip(), quote=evidence.text.strip(),
            ),)

    broad = KnowledgeScope(knowledge_base_ids=frozenset({"demo"}))
    snapshot = update_wiki(corpus, broad, Extractor()).snapshot
    return KnowledgeRetriever(corpus, scope, wiki=snapshot)


def test_wiki_agent_read_exposes_only_actual_source_quotes(corpus):
    scope = KnowledgeScope(knowledge_base_ids=frozenset({"demo"}))
    retriever = _wiki_retriever(corpus, scope)
    env = KnowledgeEnvironment(retriever)
    assert {tool.name for tool in env.tool_specs()} == {
        "search_knowledge", "read_document", "list_documents", "wiki_search", "wiki_read_page"
    }
    env.reset(spec())
    found = env.execute(ToolCall(call_id="w1", name="wiki_search", arguments={"query": "Projection"}))
    assert found.ok and found.payload["pages"]
    assert not found.details["evidence_ids"]
    page_id = found.payload["pages"][0]["page_id"]
    page = env.execute(ToolCall(call_id="w2", name="wiki_read_page",
                                arguments={"page_id": page_id, "limit": 1}))
    assert page.ok and len(page.payload["claims"]) == 1
    source = page.payload["claims"][0]["sources"][0]
    assert source["citation"] == f"[{source['chunk_id']}]"
    assert source["quote"] in retriever.chunks[source["chunk_id"]].text
    assert source["chunk_id"] in env.trace()["evidence_ids"]
    assert check_knowledge_citations(source["citation"], env.trace()["evidence_ids"]).ok


def test_wiki_agent_cannot_expand_document_scope(corpus):
    allowed = next(row for row in corpus.documents if row.source == "projection.md")
    scope = KnowledgeScope(
        knowledge_base_ids=frozenset({"demo"}), document_ids=frozenset({allowed.document_id})
    )
    retriever = _wiki_retriever(corpus, scope)
    env = KnowledgeEnvironment(retriever)
    env.reset(spec())
    page_id = retriever.wiki.pages[0].page_id
    result = env.execute(ToolCall(call_id="w1", name="wiki_read_page",
                                  arguments={"page_id": page_id}))
    assert result.ok
    assert all(item["document_id"] == allowed.document_id for claim in result.payload["claims"]
               for item in claim["sources"])
    invalid = env.execute(ToolCall(call_id="w2", name="wiki_read_page",
                                   arguments={"page_id": "w_unknown"}))
    assert not invalid.ok
    assert env.trace()["evidence_ids"]


def test_in_document_query_agent_exposes_only_matching_chunks(retriever):
    document = next(row for row in retriever.documents.values() if row.source == "least-squares.md")
    env = KnowledgeEnvironment(retriever)
    env.reset(spec())
    result = env.execute(ToolCall(call_id="q1", name="read_document",
                                  arguments={"id": document.document_id, "query": "QR 分解"}))
    assert result.ok and result.payload["evidence"]
    assert all("QR" in item["text"] for item in result.payload["evidence"])
    assert result.payload["next_offset"] is None
