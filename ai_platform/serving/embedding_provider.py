from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from ai_platform.observability.usage_tracker import JsonlUsageTracker, UsageEvent, get_env_usage_tracker
from ai_platform.shared.mock_embedding import MockEmbeddingProvider


class EmbeddingProvider(Protocol):
    """Boundary for production or mock embedding providers.

    Real providers should implement this interface without changing retrieval or
    preprocessing code. Production API keys, billing, retries, and rate limits are
    intentionally not wired in this isolated prototype.
    """

    name: str
    dimensions: int

    def embed_query(self, text: str) -> list[float]:
        ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...


@dataclass(frozen=True)
class EmbeddingRequest:
    texts: list[str]
    purpose: str = "retrieval"


@dataclass(frozen=True)
class EmbeddingResponse:
    provider: str
    dimensions: int
    vectors: list[list[float]]


class MockServingEmbeddingProvider:
    name = "mock-hashed-embedding"

    def __init__(self, dimensions: int = 128) -> None:
        self._model = MockEmbeddingProvider(dimensions=dimensions)
        self.dimensions = dimensions

    def embed_query(self, text: str) -> list[float]:
        return self._model.embed_query(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._model.embed_documents(texts)

    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        return EmbeddingResponse(
            provider=self.name,
            dimensions=self.dimensions,
            vectors=self.embed_documents(request.texts),
        )


def get_mock_embedding_provider(*, dimensions: int = 128) -> MockServingEmbeddingProvider:
    return MockServingEmbeddingProvider(dimensions=dimensions)


class OpenAICompatibleEmbeddingProvider:
    """OpenAI-compatible embedding provider for isolated API smoke tests.

    It is optional and only reads configuration from environment variables. The
    default StudyCopilot path continues to use the deterministic mock provider.
    """

    name = "openai-compatible-embedding"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        dimensions: int | None = None,
        timeout_seconds: float = 30.0,
        usage_tracker: JsonlUsageTracker | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        if not api_key:
            raise ValueError("api_key is required")
        if not model:
            raise ValueError("model is required")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.dimensions = dimensions or 0
        self.timeout_seconds = timeout_seconds
        self.usage_tracker = usage_tracker

    def embed_query(self, text: str) -> list[float]:
        vectors = self.embed_documents([text])
        return vectors[0] if vectors else []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        response = self.embed(EmbeddingRequest(texts=texts))
        return response.vectors

    def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        payload: dict[str, object] = {
            "model": self.model,
            "input": request.texts,
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        http_request = urllib.request.Request(
            f"{self.base_url}/embeddings",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.URLError as exc:
            self._record_usage(
                status="error",
                operation="embeddings",
                input_count=len(request.texts),
                error_type=exc.__class__.__name__,
            )
            raise RuntimeError("embedding provider request failed") from exc
        data = json.loads(raw)
        vectors = _parse_embedding_vectors(data)
        dimensions = len(vectors[0]) if vectors else self.dimensions
        usage = data.get("usage") if isinstance(data, dict) else {}
        total_tokens = int((usage or {}).get("total_tokens") or 0) if isinstance(usage, dict) else 0
        self._record_usage(
            status="success",
            operation="embeddings",
            total_tokens=total_tokens,
            input_count=len(request.texts),
            output_count=len(vectors),
        )
        return EmbeddingResponse(provider=self.name, dimensions=dimensions, vectors=vectors)

    def _record_usage(
        self,
        *,
        status: str,
        operation: str,
        total_tokens: int = 0,
        input_count: int = 0,
        output_count: int = 0,
        error_type: str | None = None,
    ) -> None:
        if not self.usage_tracker:
            return
        self.usage_tracker.record(
            UsageEvent(
                provider=self.name,
                model=self.model,
                operation=operation,
                status=status,
                total_tokens=total_tokens,
                input_count=input_count,
                output_count=output_count,
                error_type=error_type,
            )
        )


def get_env_embedding_provider(prefix: str = "STUDYHUB_EMBEDDING") -> OpenAICompatibleEmbeddingProvider | None:
    base_url = os.getenv(f"{prefix}_BASE_URL")
    api_key = os.getenv(f"{prefix}_API_KEY")
    model = os.getenv(f"{prefix}_MODEL")
    dimensions = os.getenv(f"{prefix}_DIMENSIONS")
    if not base_url or not api_key or not model:
        return None
    parsed_dimensions = int(dimensions) if dimensions and dimensions.isdigit() else None
    return OpenAICompatibleEmbeddingProvider(
        base_url=base_url,
        api_key=api_key,
        model=model,
        dimensions=parsed_dimensions,
        usage_tracker=get_env_usage_tracker(),
    )


def _parse_embedding_vectors(data: object) -> list[list[float]]:
    if not isinstance(data, dict):
        raise ValueError("embedding response must be a JSON object")
    raw_items = data.get("data")
    if not isinstance(raw_items, list):
        raise ValueError("embedding response data must be a list")
    sorted_items = sorted(
        (item for item in raw_items if isinstance(item, dict)),
        key=lambda item: int(item.get("index") or 0),
    )
    vectors: list[list[float]] = []
    for item in sorted_items:
        raw_embedding = item.get("embedding")
        if not isinstance(raw_embedding, list):
            raise ValueError("embedding item is missing embedding list")
        vectors.append([float(value) for value in raw_embedding])
    return vectors
