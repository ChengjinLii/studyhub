from __future__ import annotations

import pytest

from tests.support import build_auth_headers, seed_read_users


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("post", "/api/ai/chat", {"messages": [{"role": "user", "content": "通信原理怎么复习"}]}),
        ("post", "/api/ai-chats", {"messages": [{"role": "user", "content": "通信原理怎么复习"}]}),
        ("post", "/api/ai/recommend", {"query": "通信原理往年题常考什么"}),
        ("post", "/api/ai-recommendations", {"query": "通信原理往年题常考什么"}),
        ("get", "/api/ai/memory", None),
        ("put", "/api/ai/memory-preferences", {"enabled": False}),
        ("delete", "/api/ai/memory", None),
        ("post", "/api/ai/feedback", {"hook": "useful", "selectedMaterialIds": []}),
    ],
)
def test_ai_routes_require_admin_or_developer(client, auth_service, method: str, path: str, json_body: dict[str, object] | None) -> None:
    seed_read_users(auth_service)

    request_kwargs: dict[str, object] = {"headers": build_auth_headers(1, 1)}
    if json_body is not None:
        request_kwargs["json"] = json_body
    response = client.request(method.upper(), path, **request_kwargs)

    assert response.status_code == 403
    assert response.json()["error"] == {"code": "无权访问管理接口", "message": "无权访问管理接口"}


def test_ai_chat_allows_admin(client, auth_service) -> None:
    seed_read_users(auth_service)

    response = client.post(
        "/api/ai/chat",
        headers=build_auth_headers(3, 8),
        json={"messages": [{"role": "user", "content": "通信原理怎么复习"}]},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
