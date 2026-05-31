from __future__ import annotations

from pathlib import Path
import sys


AI_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AI_PLATFORM_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_platform.serving.llm_provider import ChatCompletionRequest, ChatMessage, OpenAICompatibleChatProvider, get_env_chat_provider


def test_env_chat_provider_is_optional_when_not_configured(monkeypatch) -> None:
    monkeypatch.delenv("STUDYHUB_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("STUDYHUB_LLM_API_KEY", raising=False)
    monkeypatch.delenv("STUDYHUB_LLM_MODEL", raising=False)

    assert get_env_chat_provider() is None


def test_openai_compatible_payload_contract(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self) -> bytes:
            return b'{"choices":[{"message":{"content":"{\\"intent\\":\\"material_search\\"}"}}],"usage":{"prompt_tokens":3,"completion_tokens":5,"total_tokens":8}}'

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = request.data.decode("utf-8")
        captured["timeout"] = timeout
        captured["authorization"] = request.headers["Authorization"]
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = OpenAICompatibleChatProvider(
        base_url="https://example.test/v1",
        api_key="test-key",
        model="test-model",
        timeout_seconds=3,
    )

    response = provider.complete(
        ChatCompletionRequest(
            messages=[ChatMessage(role="user", content="只返回 JSON")],
            response_format={"type": "json_object"},
        )
    )

    assert captured["url"] == "https://example.test/v1/chat/completions"
    assert '"model": "test-model"' in str(captured["body"])
    assert captured["authorization"] == "Bearer test-key"
    assert response.content == '{"intent":"material_search"}'
    assert response.usage["totalTokens"] == 8
