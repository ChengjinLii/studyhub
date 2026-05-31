from __future__ import annotations

from pathlib import Path
import sys


AI_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AI_PLATFORM_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_platform.agents.genrec_agent import GenRecAgent
from ai_platform.retrieval.semantic_search import InMemorySemanticSearch
from ai_platform.scripts.semantic_search_demo import DEFAULT_SAMPLE_PATH, load_documents
from ai_platform.serving.llm_provider import ChatCompletionResponse


class FakeChatProvider:
    name = "fake-chat"
    model = "fake-model"

    def __init__(self, content: str) -> None:
        self.content = content

    def complete(self, _request):
        return ChatCompletionResponse(provider=self.name, model=self.model, content=self.content, usage={})


def _agent(provider: FakeChatProvider) -> GenRecAgent:
    return GenRecAgent(InMemorySemanticSearch(load_documents(DEFAULT_SAMPLE_PATH)), chat_provider=provider)


def test_genrec_uses_llm_composition_when_ids_are_grounded() -> None:
    response = _agent(
        FakeChatProvider(
            '{"answer":"先看真题资料，再参考备考经验。","recommendedItems":[{"id":"material-001","reason":"和通信原理期末真题直接相关。"}],"studyPlan":[{"dayRange":"第 1-3 天","task":"阅读 material-001 并整理重点。"}]}'
        )
    ).run("我两周后考通信原理，基础一般，想找速成资料和真题解析。")

    payload = response.to_dict()

    assert payload["answer"] == "先看真题资料，再参考备考经验。"
    assert payload["recommendedItems"][0]["id"] == "material-001"
    assert payload["recommendedItems"][0]["reason"] == "和通信原理期末真题直接相关。"
    assert payload["studyPlan"][0]["task"] == "阅读 material-001 并整理重点。"


def test_genrec_falls_back_when_llm_invents_candidate_id() -> None:
    response = _agent(
        FakeChatProvider(
            '{"answer":"推荐一个不存在的资料。","recommendedItems":[{"id":"made-up-id","reason":"不存在。"}],"studyPlan":[]}'
        )
    ).run("我两周后考通信原理，基础一般，想找速成资料和真题解析。")

    payload = response.to_dict()
    cited_ids = {item["id"] for item in payload["recommendedItems"]}
    reranked_ids = {item["id"] for item in payload["rerankedCandidates"]}

    assert cited_ids
    assert cited_ids <= reranked_ids
    assert "不存在" not in payload["answer"]
