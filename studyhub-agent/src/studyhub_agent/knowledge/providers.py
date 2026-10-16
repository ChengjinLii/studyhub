from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Protocol
from urllib.parse import urlsplit

import httpx


class KnowledgeBackendError(RuntimeError):
    """A retrieval dependency failed; this is not an empty search result."""


class Embedder(Protocol):
    identity: str

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


class Reranker(Protocol):
    identity: str

    def score(self, query: str, passages: Sequence[str]) -> Sequence[float]: ...


def vectors(values: Sequence[Sequence[float]], count: int) -> list[tuple[float, ...]]:
    try:
        rows = [tuple(float(value) for value in row) for row in values]
    except (TypeError, ValueError, OverflowError) as exc:
        raise KnowledgeBackendError("embedding returned invalid vectors") from exc
    if len(rows) != count or not rows or not rows[0] or any(len(row) != len(rows[0]) for row in rows):
        raise KnowledgeBackendError("embedding returned an invalid count or inconsistent dimensions")
    if any(not math.isfinite(value) for row in rows for value in row):
        raise KnowledgeBackendError("embedding returned non-finite values")
    if any(not math.isfinite(math.hypot(*row)) or math.hypot(*row) == 0 for row in rows):
        raise KnowledgeBackendError("embedding returned a zero or overflowing vector")
    return rows


class _HttpProvider:
    def __init__(
        self, endpoint: str, model: str, *, api_key: str | None = None, client: httpx.Client | None = None
    ) -> None:
        url = urlsplit(endpoint)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query:
            raise ValueError("model endpoint must be an HTTP(S) URL without credentials or query")
        if not model.strip() or url.fragment:
            raise ValueError("a model identifier and an endpoint without fragment are required")
        self.identity = f"{model}@{endpoint}"
        self._endpoint, self._model = endpoint, model
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = client or httpx.Client(timeout=60, trust_env=False)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _post(self, body: dict):
        try:
            response = self._client.post(self._endpoint, json=body, headers=self._headers)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise KnowledgeBackendError("model endpoint request failed") from exc


class HttpEmbedder(_HttpProvider):
    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        if not texts:
            return []
        body = self._post({"model": self._model, "input": list(texts)})
        try:
            rows = sorted(body["data"], key=lambda row: row["index"])
            if [row["index"] for row in rows] != list(range(len(texts))):
                raise ValueError("embedding indices are incomplete or duplicated")
            return vectors([row["embedding"] for row in rows], len(texts))
        except (KeyError, TypeError, ValueError) as exc:
            raise KnowledgeBackendError("invalid embedding response") from exc


class HttpReranker(_HttpProvider):
    def score(self, query: str, passages: Sequence[str]) -> Sequence[float]:
        if not passages:
            return []
        body = self._post({"model": self._model, "query": query, "documents": list(passages)})
        try:
            rows = sorted(body["results"], key=lambda row: row["index"])
            if [row["index"] for row in rows] != list(range(len(passages))):
                raise ValueError("rerank indices are incomplete or duplicated")
            scores = [float(row["relevance_score"]) for row in rows]
            if any(not math.isfinite(score) for score in scores):
                raise ValueError("non-finite rerank score")
            return scores
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise KnowledgeBackendError("invalid rerank response") from exc
