from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_mcp_protocol import MCP_HEADERS


def mcp_method(client: TestClient, method: str, params: dict | None = None):
    return client.post(
        "/mcp",
        headers=MCP_HEADERS,
        json={"jsonrpc": "2.0", "id": 20, "method": method, "params": params or {}},
    )


def test_mcp_does_not_expose_resources_or_prompts(client: TestClient) -> None:
    for method, params in (
        ("resources/templates/list", {}),
        ("resources/read", {"uri": "studyhub://materials/101"}),
        ("prompts/list", {}),
    ):
        response = mcp_method(client, method, params)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "MCP_FORBIDDEN"
