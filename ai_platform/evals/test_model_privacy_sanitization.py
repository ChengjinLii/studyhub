from __future__ import annotations

from pathlib import Path
import sys


AI_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AI_PLATFORM_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_platform.agents.genrec_agent import GenRecAgent
from ai_platform.retrieval.semantic_search import InMemorySemanticSearch, SearchDocument, SearchResult
from ai_platform.router.query_understanding import LLMQueryUnderstandingRouter
from ai_platform.scripts.semantic_search_demo import DEFAULT_SAMPLE_PATH, load_documents
from ai_platform.serving.llm_provider import ChatCompletionResponse
from ai_platform.serving.rerank_provider import ChatRerankProvider


class CapturingChatProvider:
    name = "capture-chat"
    model = "capture-model"

    def __init__(self, response_content: str) -> None:
        self.response_content = response_content
        self.seen_messages: list[str] = []

    def complete(self, request):
        self.seen_messages.extend(message.content for message in request.messages)
        return ChatCompletionResponse(provider=self.name, model=self.model, content=self.response_content, usage={})


def _joined_messages(provider: CapturingChatProvider) -> str:
    return "\n".join(provider.seen_messages)


def test_llm_router_sanitizes_contacts_before_model_call() -> None:
    provider = CapturingChatProvider(
        '{"intent":"material_search","queryRewrite":"通信原理 期末","entities":{"course":"通信原理"},"searchTasks":[{"type":"material","query":"通信原理 期末"}]}'
    )
    router = LLMQueryUnderstandingRouter(provider)

    router.understand("我想找通信原理资料，邮箱 alice@example.com，手机 13812345678")

    messages = _joined_messages(provider)
    assert "alice@example.com" not in messages
    assert "13812345678" not in messages
    assert "[REDACTED_CONTACT]" in messages


def test_chat_rerank_sanitizes_candidate_text_before_model_call() -> None:
    provider = CapturingChatProvider('{"ranked":[{"id":"doc-1","score":0.9,"reason":"相关"}]}')
    document = SearchDocument(
        id="doc-1",
        type="material",
        title="通信原理资料",
        text="正文包含联系方式 13812345678 和 alice@example.com",
        metadata={"contact": "QQ 2731938007"},
    )
    candidate = SearchResult(document=document, score=1.0, dense_score=1.0, sparse_score=1.0)

    ChatRerankProvider(provider).rerank("通信原理 13812345678", [candidate])

    messages = _joined_messages(provider)
    assert "13812345678" not in messages
    assert "alice@example.com" not in messages
    assert "2731938007" not in messages
    assert "[REDACTED_CONTACT]" in messages


def test_genrec_composer_sanitizes_understanding_and_candidates_before_model_call() -> None:
    provider = CapturingChatProvider(
        '{"answer":"推荐 material-001。","recommendedItems":[{"id":"material-001","reason":"匹配通信原理。"}],"studyPlan":[]}'
    )
    searcher = InMemorySemanticSearch(load_documents(DEFAULT_SAMPLE_PATH))

    GenRecAgent(searcher, chat_provider=provider).run("我想找通信原理资料，电话 13812345678")

    messages = _joined_messages(provider)
    assert "13812345678" not in messages
    assert "[REDACTED_CONTACT]" in messages
