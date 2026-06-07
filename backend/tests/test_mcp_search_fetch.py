from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.mcp.serializers import material_url
from tests.test_mcp_protocol import MCP_HEADERS


MCP_SENSITIVE_KEYS = {"raw", "netdiskUrl", "netdiskPassword", "contactValue", "contactType"}
MATERIAL_PUBLIC_KEYS = {
    "id",
    "title",
    "description",
    "school",
    "college",
    "major",
    "tags",
    "free",
    "downloadCount",
    "ratingAvg",
    "ratingCount",
    "previewManifest",
    "previewWatermarkEnabled",
    "previewSource",
}
REQUEST_PUBLIC_KEYS = {
    "id",
    "course",
    "keyword",
    "school",
    "college",
    "major",
    "budget",
    "fundedAmount",
    "responseCount",
    "status",
    "createdAt",
}
MARKET_PUBLIC_KEYS = {"id", "title", "description", "school", "category", "price", "wantCount", "status"}


def assert_no_sensitive_mcp_keys(value) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            assert key not in MCP_SENSITIVE_KEYS
            assert_no_sensitive_mcp_keys(child)
    elif isinstance(value, list):
        for item in value:
            assert_no_sensitive_mcp_keys(item)


def assert_fetch_contract(structured: dict, *, resource_id: str, public_keys: set[str]) -> None:
    assert set(structured) == {"id", "title", "text", "url", "metadata"}
    assert structured["id"] == resource_id
    assert isinstance(structured["title"], str)
    assert isinstance(structured["text"], str)
    assert structured["url"].startswith("https://")
    assert set(structured["metadata"]) == {"type", "public"}
    assert set(structured["metadata"]["public"]) == public_keys


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
    assert_fetch_contract(structured, resource_id="material:101", public_keys=MATERIAL_PUBLIC_KEYS)
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
    assert_fetch_contract(response.json()["result"]["structuredContent"], resource_id="market:201", public_keys=MARKET_PUBLIC_KEYS)
    assert_no_sensitive_mcp_keys(response.json())


def test_mcp_fetch_request_uses_public_contract(client: TestClient) -> None:
    response = call_tool(client, "fetch", {"id": "request:401"})

    assert response.status_code == 200
    structured = response.json()["result"]["structuredContent"]
    assert_fetch_contract(structured, resource_id="request:401", public_keys=REQUEST_PUBLIC_KEYS)
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
    assert set(materials.json()["result"]["structuredContent"]["items"][0]) == MATERIAL_PUBLIC_KEYS
    assert set(requests.json()["result"]["structuredContent"]["items"][0]) == REQUEST_PUBLIC_KEYS
    assert set(market.json()["result"]["structuredContent"]["items"][0]) == MARKET_PUBLIC_KEYS
    assert_no_sensitive_mcp_keys(materials.json())
    assert_no_sensitive_mcp_keys(requests.json())
    assert_no_sensitive_mcp_keys(market.json())


def test_mcp_get_tools_use_fixed_public_schema(client: TestClient) -> None:
    material = call_tool(client, "materials.get", {"id": 101})
    request = call_tool(client, "requests.get", {"id": 401})
    market = call_tool(client, "market.get", {"id": 201})

    assert material.status_code == 200
    assert request.status_code == 200
    assert market.status_code == 200
    assert set(material.json()["result"]["structuredContent"]) == MATERIAL_PUBLIC_KEYS
    assert set(request.json()["result"]["structuredContent"]) == REQUEST_PUBLIC_KEYS
    assert set(market.json()["result"]["structuredContent"]) == MARKET_PUBLIC_KEYS
    assert_no_sensitive_mcp_keys(material.json())
    assert_no_sensitive_mcp_keys(request.json())
    assert_no_sensitive_mcp_keys(market.json())


def test_mcp_contributor_leaderboard_uses_fixed_public_schema(client: TestClient) -> None:
    response = call_tool(client, "leaderboard.contributors", {"limit": 3, "period": "all"})

    assert response.status_code == 200
    items = response.json()["result"]["structuredContent"]["items"]
    assert items
    assert set(items[0]) == {"userId", "username", "downloads", "roleMask"}
    assert isinstance(items[0]["userId"], int)
    assert isinstance(items[0]["downloads"], int)
    assert isinstance(items[0]["roleMask"], int)


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
