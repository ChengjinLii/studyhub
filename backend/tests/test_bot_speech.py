from __future__ import annotations

from fastapi.testclient import TestClient

from app.services.auth_service import AuthService
from tests.support import build_auth_headers, seed_read_users


def test_bot_speech_is_public_and_only_administrators_can_update_it(
    client: TestClient,
    auth_service: AuthService,
) -> None:
    seed_read_users(auth_service)

    initial = client.get("/api/bot-speech")
    assert initial.status_code == 200
    assert initial.headers["cache-control"] == "no-store"
    assert initial.json()["data"] == {"enabled": False, "message": "", "updatedAt": None}

    anonymous_update = client.put(
        "/api/admin/bot-speech",
        json={"enabled": True, "message": "匿名用户不能发布"},
    )
    assert anonymous_update.status_code == 401

    user_update = client.put(
        "/api/admin/bot-speech",
        headers=build_auth_headers(1, 1),
        json={"enabled": True, "message": "普通用户不能发布"},
    )
    assert user_update.status_code == 403

    published = client.put(
        "/api/admin/bot-speech",
        headers=build_auth_headers(3, 8),
        json={"enabled": True, "message": "  今天也要认真学习！  "},
    )
    assert published.status_code == 200
    published_data = published.json()["data"]
    assert published_data["enabled"] is True
    assert published_data["message"] == "今天也要认真学习！"
    assert published_data["updatedAt"]

    public_config = client.get("/api/bot-speech")
    assert public_config.status_code == 200
    assert public_config.json()["data"] == published_data

    empty_enabled = client.put(
        "/api/admin/bot-speech",
        headers=build_auth_headers(3, 8),
        json={"enabled": True, "message": "   "},
    )
    assert empty_enabled.status_code == 400

    disabled = client.put(
        "/api/admin/bot-speech",
        headers=build_auth_headers(3, 8),
        json={"enabled": False, "message": ""},
    )
    assert disabled.status_code == 200
    assert disabled.json()["data"]["enabled"] is False
