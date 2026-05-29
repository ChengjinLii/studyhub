from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.mcp.serializers import material_url
from tests.test_mcp_protocol import MCP_HEADERS


MCP_SENSITIVE_KEYS = {"raw", "netdiskUrl", "netdiskPassword", "contactValue", "contactType"}


def assert_no_sensitive_mcp_keys(value) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            assert key not in MCP_SENSITIVE_KEYS
            assert_no_sensitive_mcp_keys(child)
    elif isinstance(value, list):
        for item in value:
            assert_no_sensitive_mcp_keys(item)


def call_tool(client: TestClient, name: str, arguments: dict | None = None, headers: dict[str, str] | None = None):
    request_headers = {**MCP_HEADERS, **(headers or {})}
    return client.post(
        "/mcp",
        headers=request_headers,
        json={
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        },
    )


def test_mcp_search_returns_mixed_studyhub_results(client: TestClient) -> None:
    response = call_tool(client, "search", {"query": "数据结构", "limit": 10})

    assert response.status_code == 200
    result = response.json()["result"]
    structured = result["structuredContent"]
    assert structured["results"]
    ids = {item["id"] for item in structured["results"]}
    assert any(item_id.startswith("material:") for item_id in ids)
    assert result["content"][0]["type"] == "text"
    assert '"results"' in result["content"][0]["text"]


def test_mcp_fetch_material_returns_full_structured_content(client: TestClient) -> None:
    response = call_tool(client, "fetch", {"id": "material:101"})

    assert response.status_code == 200
    result = response.json()["result"]
    structured = result["structuredContent"]
    assert structured["id"] == "material:101"
    assert structured["title"] == "数据结构期末真题解析"
    assert "text" in structured
    assert structured["metadata"]["type"] == "material"
    assert "raw" not in structured["metadata"]
    assert "public" in structured["metadata"]
    assert "netdiskUrl" not in structured["metadata"]["public"]
    assert "netdiskPassword" not in structured["metadata"]["public"]
    assert_no_sensitive_mcp_keys(result)
    assert result["content"][0]["type"] == "text"
    assert "数据结构期末真题解析" in result["content"][0]["text"]


def test_mcp_fetch_market_does_not_expose_contact_value(client: TestClient) -> None:
    response = call_tool(client, "fetch", {"id": "market:201"})

    assert response.status_code == 200
    public = response.json()["result"]["structuredContent"]["metadata"]["public"]
    assert "contactValue" not in public
    assert "contactType" not in public
    assert_no_sensitive_mcp_keys(response.json())


def test_mcp_search_no_match_returns_empty_related_results(client: TestClient) -> None:
    response = call_tool(client, "market.search", {"query": "不存在的火星集市商品xyz", "limit": 2})

    assert response.status_code == 200
    structured = response.json()["result"]["structuredContent"]
    assert structured["items"] == []
    assert "未找到" in structured["message"]


def test_mcp_specific_read_tools_return_structured_content(client: TestClient) -> None:
    materials = call_tool(client, "materials.search", {"query": "通信", "limit": 2})
    requests = call_tool(client, "requests.search", {"query": "概率论", "limit": 2})
    market = call_tool(client, "market.search", {"query": "教材", "limit": 2})

    assert materials.status_code == 200
    assert requests.status_code == 200
    assert market.status_code == 200
    assert materials.json()["result"]["structuredContent"]["items"]
    assert requests.json()["result"]["structuredContent"]["items"]
    assert market.json()["result"]["structuredContent"]["items"]


def test_mcp_tool_call_records_safe_metrics(client: TestClient) -> None:
    response = call_tool(client, "health.ready")

    assert response.status_code == 200
    metrics = client.get("/api/metrics")
    assert metrics.status_code == 200
    assert 'studyhub_mcp_tool_calls_total{tool="health.ready",status="ok"}' in metrics.text


def test_mcp_public_urls_use_configured_site_base_url(monkeypatch) -> None:
    monkeypatch.setenv("STUDYHUB_PUBLIC_SITE_BASE_URL", "https://example.edu/studyhub/")
    get_settings.cache_clear()

    try:
        assert material_url(101) == "https://example.edu/studyhub/materials/101"
    finally:
        get_settings.cache_clear()
