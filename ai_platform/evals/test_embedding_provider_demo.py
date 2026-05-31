from __future__ import annotations

from pathlib import Path
import sys


AI_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = AI_PLATFORM_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_platform.serving.embedding_provider import EmbeddingRequest, get_mock_embedding_provider


def test_mock_embedding_provider_returns_stable_dimensions() -> None:
    provider = get_mock_embedding_provider(dimensions=32)

    response = provider.embed(EmbeddingRequest(texts=["通信原理", "数据结构"]))

    assert response.provider == "mock-hashed-embedding"
    assert response.dimensions == 32
    assert len(response.vectors) == 2
    assert all(len(vector) == 32 for vector in response.vectors)


def test_mock_embedding_provider_is_deterministic() -> None:
    provider = get_mock_embedding_provider(dimensions=16)

    first = provider.embed_query("通信原理")
    second = provider.embed_query("通信原理")

    assert first == second
