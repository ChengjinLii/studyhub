from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_mcp_protocol import MCP_HEADERS


def mcp_method(client: TestClient, method: str, params: dict | None = None):
    return client.post(
        "/mcp",
        headers=MCP_HEADERS,
        json={"jsonrpc": "2.0", "id": 20, "method": method, "params": params or {}},
    )


def test_mcp_resource_templates_include_studyhub_uris(client: TestClient) -> None:
    response = mcp_method(client, "resources/templates/list")

    assert response.status_code == 200
    templates = response.json()["result"]["resourceTemplates"]
    uris = {template["uriTemplate"] for template in templates}
    assert "studyhub://materials/{id}" in uris
    assert "studyhub://requests/{id}" in uris
    assert "studyhub://market/{id}" in uris
    assert "studyhub://users/{id}" in uris


def test_mcp_read_material_resource_returns_text(client: TestClient) -> None:
    response = mcp_method(client, "resources/read", {"uri": "studyhub://materials/101"})

    assert response.status_code == 200
    contents = response.json()["result"]["contents"]
    assert contents[0]["uri"] == "studyhub://materials/101"
    assert contents[0]["mimeType"] == "text/markdown"
    assert "数据结构期末真题解析" in contents[0]["text"]


def test_mcp_prompts_list_contains_studyhub_templates(client: TestClient) -> None:
    response = mcp_method(client, "prompts/list")

    assert response.status_code == 200
    prompts = response.json()["result"]["prompts"]
    names = {prompt["name"] for prompt in prompts}
    assert {
        "find_study_materials",
        "summarize_material",
        "compare_materials",
        "draft_material_request",
        "draft_market_listing",
        "admin_review_report",
    }.issubset(names)
