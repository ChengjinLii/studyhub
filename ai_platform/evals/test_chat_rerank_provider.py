from __future__ import annotations

from pathlib import Path
import sys


AI_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AI_PLATFORM_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_platform.retrieval.semantic_search import InMemorySemanticSearch
from ai_platform.scripts.semantic_search_demo import DEFAULT_SAMPLE_PATH, load_documents
from ai_platform.serving.llm_provider import ChatCompletionResponse
from ai_platform.serving.rerank_provider import ChatRerankProvider, MockRerankProvider


class FakeChatProvider:
    name = "fake-chat"
    model = "fake-model"

    def __init__(self, content: str, *, should_fail: bool = False) -> None:
        self.content = content
        self.should_fail = should_fail

    def complete(self, _request):
        if self.should_fail:
            raise RuntimeError("forced failure")
        return ChatCompletionResponse(provider=self.name, model=self.model, content=self.content, usage={})


def _candidates():
    searcher = InMemorySemanticSearch(load_documents(DEFAULT_SAMPLE_PATH))
    return searcher.search("高等数学 真题解析 求购", type_filter="request", top_k=3)


def test_chat_rerank_provider_accepts_grounded_candidate_ids() -> None:
    candidates = _candidates()
    provider = ChatRerankProvider(
        FakeChatProvider(
            '{"ranked":[{"id":"request-003","score":0.97,"reason":"高数下真题解析求购最匹配。"},{"id":"request-001","score":0.3,"reason":"也是期末卷求购。"}]}'
        )
    )

    results = provider.rerank("高等数学 真题解析 求购", candidates, top_k=2)

    assert results[0].search_result.document.id == "request-003"
    assert results[0].score == 0.97
    assert results[0].reason == "高数下真题解析求购最匹配。"


def test_chat_rerank_provider_falls_back_on_invalid_ids() -> None:
    candidates = _candidates()
    fallback = MockRerankProvider().rerank("高等数学 真题解析 求购", candidates, top_k=2)
    provider = ChatRerankProvider(FakeChatProvider('{"ranked":[{"id":"made-up","score":1.0}]}'))

    results = provider.rerank("高等数学 真题解析 求购", candidates, top_k=2)

    assert [result.search_result.document.id for result in results] == [
        result.search_result.document.id for result in fallback
    ]


def test_chat_rerank_provider_falls_back_on_provider_failure() -> None:
    candidates = _candidates()
    provider = ChatRerankProvider(FakeChatProvider("{}", should_fail=True))

    results = provider.rerank("高等数学 真题解析 求购", candidates, top_k=2)

    assert results
    assert results[0].search_result.document.id == "request-003"
