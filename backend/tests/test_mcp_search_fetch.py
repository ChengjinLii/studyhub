from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.mcp.serializers import material_url
from tests.test_mcp_protocol import MCP_HEADERS


MCP_SENSITIVE_KEYS = {
    "raw",
    "netdiskUrl",
    "netdiskPassword",
    "contactValue",
    "contactType",
    "downloadUrl",
    "fileStorageKey",
    "previewToken",
    "assetToken",
    "rawFileUrl",
    "fullText",
    "pdfText",
    "previewManifest",
    "previewSource",
}
DISCOVERY_MATERIAL_KEYS = {
    "materialId",
    "title",
    "summary",
    "school",
    "college",
    "major",
    "courseCategory",
    "gradeValue",
    "tags",
    "free",
    "price",
    "ratingAvg",
    "ratingCount",
    "downloadCount",
    "viewCount",
    "uploaderDisplayName",
    "url",
    "reason",
}


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


def test_mcp_material_search_returns_ranked_referral_only_results(client: TestClient) -> None:
    response = call_tool(
        client,
        "materials.search",
        {"query": "期末 真题", "course": "数据结构", "goal": "考试复习", "limit": 3},
    )

    assert response.status_code == 200
    structured = response.json()["result"]["structuredContent"]
    assert structured["items"]
    assert "下载" in structured["message"]
    for item in structured["items"]:
        assert set(item) == DISCOVERY_MATERIAL_KEYS
        assert item["url"].startswith("https://")
        assert "ref=mcp" in item["url"]
    assert_no_sensitive_mcp_keys(response.json())


def test_mcp_material_detail_always_returns_studyhub_page_link(client: TestClient) -> None:
    response = call_tool(client, "materials.get", {"material_id": 101})

    assert response.status_code == 200
    detail = response.json()["result"]["structuredContent"]
    assert set(detail) == DISCOVERY_MATERIAL_KEYS
    assert detail["materialId"] == 101
    assert detail["title"] == "数据结构期末真题解析"
    assert detail["url"].endswith("/materials/101?ref=mcp")
    assert_no_sensitive_mcp_keys(response.json())


def test_mcp_material_recommendation_uses_goal_and_returns_links(client: TestClient) -> None:
    response = call_tool(
        client,
        "materials.recommend",
        {
            "query": "基础一般",
            "course": "数据结构",
            "goal": "两周后期末考试",
            "time_budget": "14 天，每天 2 小时",
            "limit": 2,
        },
    )

    assert response.status_code == 200
    items = response.json()["result"]["structuredContent"]["items"]
    assert items
    assert all(item["url"].startswith("https://") for item in items)
    assert all(item["reason"] for item in items)
    assert_no_sensitive_mcp_keys(response.json())


def test_mcp_platform_policy_returns_public_policy_links(client: TestClient) -> None:
    response = call_tool(client, "platform.policy", {"question": "付费资料如何下载？"})

    assert response.status_code == 200
    structured = response.json()["result"]["structuredContent"]
    assert structured["policies"]
    assert structured["url"].startswith("https://")
    assert all(item["url"].startswith("https://") for item in structured["policies"])
    assert_no_sensitive_mcp_keys(response.json())


def test_mcp_tool_call_records_safe_metrics(client: TestClient) -> None:
    response = call_tool(client, "materials.search", {"query": "数据结构", "limit": 1})

    assert response.status_code == 200
    metrics = client.get("/api/metrics")
    assert metrics.status_code == 200
    assert 'studyhub_mcp_tool_calls_total{tool="materials.search",status="ok"}' in metrics.text


def test_mcp_public_urls_use_configured_site_base_url(monkeypatch) -> None:
    monkeypatch.setenv("STUDYHUB_PUBLIC_SITE_BASE_URL", "https://example.edu/studyhub/")
    get_settings.cache_clear()

    try:
        assert material_url(101) == "https://example.edu/studyhub/materials/101"
    finally:
        get_settings.cache_clear()
