from __future__ import annotations

import json
from pathlib import Path
import sys


AI_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AI_PLATFORM_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_platform.observability.usage_tracker import JsonlUsageTracker, UsageEvent, get_env_usage_tracker
from ai_platform.serving.embedding_provider import EmbeddingRequest, OpenAICompatibleEmbeddingProvider
from ai_platform.serving.llm_provider import ChatCompletionRequest, ChatMessage, OpenAICompatibleChatProvider


def test_usage_tracker_records_metadata_only(tmp_path: Path) -> None:
    path = tmp_path / "usage.jsonl"
    tracker = JsonlUsageTracker(path)

    tracker.record(
        UsageEvent(
            provider="provider",
            model="model",
            operation="chat.completions",
            status="success",
            prompt_tokens=3,
            completion_tokens=4,
            total_tokens=7,
        )
    )

    text = path.read_text(encoding="utf-8")
    assert "provider" in text
    assert "promptTokens" in text
    assert "secret" not in text
    assert tracker.summarize()["totalTokens"] == 7


def test_env_usage_tracker_is_optional(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("STUDYHUB_USAGE_LOG_PATH", raising=False)
    assert get_env_usage_tracker() is None

    path = tmp_path / "usage.jsonl"
    monkeypatch.setenv("STUDYHUB_USAGE_LOG_PATH", str(path))
    assert get_env_usage_tracker() is not None


def test_chat_provider_records_usage_without_prompt_or_key(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "usage.jsonl"

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self) -> bytes:
            return b'{"choices":[{"message":{"content":"{\\"ok\\":true}"}}],"usage":{"prompt_tokens":11,"completion_tokens":5,"total_tokens":16}}'

    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: FakeResponse())
    provider = OpenAICompatibleChatProvider(
        base_url="https://example.test/v1",
        api_key="test-secret-key",
        model="chat-model",
        usage_tracker=JsonlUsageTracker(path),
    )

    provider.complete(ChatCompletionRequest(messages=[ChatMessage(role="user", content="private prompt")]))

    text = path.read_text(encoding="utf-8")
    assert "chat.completions" in text
    assert "16" in text
    assert "private prompt" not in text
    assert "test-secret-key" not in text


def test_embedding_provider_records_usage_without_input_or_key(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "usage.jsonl"

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self) -> bytes:
            return json.dumps(
                {
                    "data": [{"index": 0, "embedding": [0.1, 0.2]}],
                    "usage": {"total_tokens": 9},
                }
            ).encode("utf-8")

    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: FakeResponse())
    provider = OpenAICompatibleEmbeddingProvider(
        base_url="https://example.test/v1",
        api_key="embedding-secret",
        model="embedding-model",
        usage_tracker=JsonlUsageTracker(path),
    )

    provider.embed(EmbeddingRequest(texts=["通信原理 private text"]))

    text = path.read_text(encoding="utf-8")
    assert "embeddings" in text
    assert "9" in text
    assert "通信原理" not in text
    assert "embedding-secret" not in text
