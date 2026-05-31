from __future__ import annotations

import json
from pathlib import Path
import sys


AI_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AI_PLATFORM_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_platform.serving.embedding_provider import EmbeddingRequest, OpenAICompatibleEmbeddingProvider, get_env_embedding_provider


def test_env_embedding_provider_is_optional_when_not_configured(monkeypatch) -> None:
    monkeypatch.delenv("STUDYHUB_EMBEDDING_BASE_URL", raising=False)
    monkeypatch.delenv("STUDYHUB_EMBEDDING_API_KEY", raising=False)
    monkeypatch.delenv("STUDYHUB_EMBEDDING_MODEL", raising=False)

    assert get_env_embedding_provider() is None


def test_openai_compatible_embedding_payload_contract(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self) -> bytes:
            return json.dumps(
                {
                    "data": [
                        {"index": 1, "embedding": [0.3, 0.4]},
                        {"index": 0, "embedding": [0.1, 0.2]},
                    ]
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = request.data.decode("utf-8")
        captured["timeout"] = timeout
        captured["authorization"] = request.headers["Authorization"]
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = OpenAICompatibleEmbeddingProvider(
        base_url="https://example.test/v1",
        api_key="test-key",
        model="embedding-model",
        timeout_seconds=3,
    )

    response = provider.embed(EmbeddingRequest(texts=["通信原理", "数据结构"]))

    assert captured["url"] == "https://example.test/v1/embeddings"
    assert '"model": "embedding-model"' in str(captured["body"])
    assert '"通信原理"' in str(captured["body"])
    assert captured["authorization"] == "Bearer test-key"
    assert response.dimensions == 2
    assert response.vectors == [[0.1, 0.2], [0.3, 0.4]]
