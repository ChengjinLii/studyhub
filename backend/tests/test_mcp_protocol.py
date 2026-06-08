from __future__ import annotations

from fastapi.testclient import TestClient


MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


def mcp_call(client: TestClient, method: str, params: dict | None = None, request_id: int = 1):
    response = client.post(
        "/mcp",
        headers=MCP_HEADERS,
        json={
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        },
    )
    return response


def test_mcp_initialize_returns_server_capabilities(client: TestClient) -> None:
    response = mcp_call(
        client,
        "initialize",
        {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "studyhub-test", "version": "0.1.0"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["jsonrpc"] == "2.0"
    assert body["id"] == 1
    assert body["result"]["serverInfo"]["name"] == "StudyHub MCP"
    assert "tools" in body["result"]["capabilities"]
    assert "resources" in body["result"]["capabilities"]
    assert "prompts" in body["result"]["capabilities"]


def test_mcp_oauth_protected_resource_metadata(client: TestClient) -> None:
    response = client.get("/.well-known/oauth-protected-resource")

    assert response.status_code == 200
    body = response.json()
    assert body["resource"].endswith("/mcp")
    assert body["bearer_methods_supported"] == ["header"]
    assert {
        "mcp:discover_public_materials",
        "mcp:recommend_public_materials",
        "mcp:read_public_material_summary",
    }.issubset(set(body["scopes_supported"]))


def test_mcp_tools_list_exposes_v0_read_tools(client: TestClient) -> None:
    response = mcp_call(client, "tools/list")

    assert response.status_code == 200
    tools = response.json()["result"]["tools"]
    names = {tool["name"] for tool in tools}
    assert {
        "search",
        "fetch",
        "materials.search",
        "materials.discover",
        "materials.get",
        "materials.summarize",
        "materials.recommend",
        "materials.recommend_public",
        "requests.search",
        "requests.get",
        "requests.leaderboard",
        "market.search",
        "market.get",
        "leaderboard.contributors",
        "health.ready",
    }.issubset(names)
    assert "materials.preview" not in names
    assert "comments.create" not in names
    assert "admin.users.search" not in names
