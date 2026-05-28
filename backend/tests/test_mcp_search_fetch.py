from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_mcp_protocol import MCP_HEADERS


def call_tool(client: TestClient, name: str, arguments: dict | None = None):
    return client.post(
        "/mcp",
        headers=MCP_HEADERS,
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
    assert any(item_id.startswith("request:") for item_id in ids)
    assert any(item_id.startswith("market:") for item_id in ids)
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
    assert result["content"][0]["type"] == "text"
    assert "数据结构期末真题解析" in result["content"][0]["text"]


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
