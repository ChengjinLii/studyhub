import json

import httpx
import pytest

from studyhub_agent.knowledge.providers import HttpEmbedder, HttpReranker, KnowledgeBackendError


def test_embedding_restores_response_order():
    def respond(request):
        assert json.loads(request.content) == {"model": "embed@1", "input": ["one", "two"]}
        assert request.headers["Authorization"] == "Bearer test-secret"
        return httpx.Response(
            200, json={"data": [{"index": 1, "embedding": [0, 1]}, {"index": 0, "embedding": [1, 0]}]}
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        provider = HttpEmbedder("http://model/v1/embeddings", "embed@1", api_key="test-secret", client=client)
        assert provider.embed(["one", "two"]) == [(1, 0), (0, 1)]
        assert provider.embed([]) == []
        provider.close()
        assert not client.is_closed


@pytest.mark.parametrize("body", [{}, {"data": []}, {"data": [{"index": 0, "embedding": [1]}] * 2}])
def test_embedding_rejects_invalid_response(body):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body))) as client:
        provider = HttpEmbedder("http://model/embeddings", "model", client=client)
        with pytest.raises(KnowledgeBackendError):
            provider.embed(["one", "two"])


def test_rerank_restores_index_order_and_rejects_partial_results():
    body = {"results": [{"index": 1, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.1}]}
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body))) as client:
        provider = HttpReranker("http://model/v1/rerank", "rank@1", client=client)
        assert provider.score("q", ["one", "two"]) == [0.1, 0.9]
        assert provider.score("q", []) == []
        body["results"].pop()
        with pytest.raises(KnowledgeBackendError):
            provider.score("q", ["one", "two"])


def test_http_errors_do_not_leak_response_or_credentials():
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(503, text="secret"))) as client:
        provider = HttpEmbedder("http://model/v1/embeddings", "model", api_key="key", client=client)
        with pytest.raises(KnowledgeBackendError, match="^model endpoint request failed$"):
            provider.embed(["x"])


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "http://user:key@model/x", "http://model/x?key=secret", "http://model/#x"]
)
def test_endpoint_configuration_rejects_unsafe_credentials_and_schemes(url):
    with pytest.raises(ValueError):
        HttpEmbedder(url, "model")
