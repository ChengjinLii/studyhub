from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.services.auth_service import AuthService
from tests.support import build_auth_headers, seed_read_users


def test_bot_speech_queue_publish_schedule_and_revoke(
    client: TestClient,
    auth_service: AuthService,
) -> None:
    seed_read_users(auth_service)
    admin_headers = build_auth_headers(3, 8)

    initial = client.get("/api/bot-speech")
    assert initial.status_code == 200
    assert initial.headers["cache-control"] == "no-store"
    assert initial.json()["data"] == {
        "enabled": False,
        "message": "",
        "updatedAt": None,
        "messages": [],
        "pollIntervalSeconds": 15,
    }

    anonymous = client.post(
        "/api/admin/bot-speech/messages",
        json={"message": "匿名用户不能发布", "publish": True},
    )
    assert anonymous.status_code == 401

    forbidden = client.post(
        "/api/admin/bot-speech/messages",
        headers=build_auth_headers(1, 1),
        json={"message": "普通用户不能发布", "publish": True},
    )
    assert forbidden.status_code == 403

    first = client.post(
        "/api/admin/bot-speech/messages",
        headers=admin_headers,
        json={
            "message": "  今天也要认真学习！  ",
            "displayStyle": "TYPEWRITER",
            "displayDurationSeconds": 5,
            "priority": 30,
            "publish": True,
        },
    )
    assert first.status_code == 201
    first_data = first.json()["data"]
    assert first_data["message"] == "今天也要认真学习！"
    assert first_data["displayStyle"] == "TYPEWRITER"
    assert first_data["status"] == "PUBLISHED"
    assert first_data["createdByUserId"] == 3

    high_priority = client.post(
        "/api/admin/bot-speech/messages",
        headers=admin_headers,
        json={
            "message": "高优先级消息",
            "displayStyle": "EMPHASIS",
            "displayDurationSeconds": 0,
            "priority": 90,
            "publish": True,
        },
    )
    assert high_priority.status_code == 201
    high_priority_data = high_priority.json()["data"]

    future = datetime.now(UTC) + timedelta(days=1)
    scheduled = client.post(
        "/api/admin/bot-speech/messages",
        headers=admin_headers,
        json={
            "message": "明天显示",
            "startsAt": future.isoformat(),
            "endsAt": (future + timedelta(hours=1)).isoformat(),
            "publish": True,
        },
    )
    assert scheduled.status_code == 201
    assert scheduled.json()["data"]["status"] == "SCHEDULED"

    draft = client.post(
        "/api/admin/bot-speech/messages",
        headers=admin_headers,
        json={"message": "暂不发布", "publish": False},
    )
    assert draft.status_code == 201
    assert draft.json()["data"]["status"] == "DRAFT"

    public_queue = client.get("/api/bot-speech").json()["data"]
    assert [item["message"] for item in public_queue["messages"]] == ["高优先级消息", "今天也要认真学习！"]
    assert public_queue["message"] == "高优先级消息"

    admin_list = client.get("/api/admin/bot-speech/messages", headers=admin_headers)
    assert admin_list.status_code == 200
    assert admin_list.json()["data"]["total"] == 4

    revoked = client.post(
        f"/api/admin/bot-speech/messages/{high_priority_data['id']}/revoke",
        headers=admin_headers,
    )
    assert revoked.status_code == 200
    assert revoked.json()["data"]["status"] == "REVOKED"
    assert revoked.json()["data"]["revokedByUserId"] == 3

    public_after_revoke = client.get("/api/bot-speech").json()["data"]
    assert [item["id"] for item in public_after_revoke["messages"]] == [first_data["id"]]

    editing_revoked = client.put(
        f"/api/admin/bot-speech/messages/{high_priority_data['id']}",
        headers=admin_headers,
        json={"message": "不能恢复", "publish": True},
    )
    assert editing_revoked.status_code == 409


def test_bot_speech_validates_display_and_schedule(client: TestClient, auth_service: AuthService) -> None:
    seed_read_users(auth_service)
    headers = build_auth_headers(3, 8)

    invalid_style = client.post(
        "/api/admin/bot-speech/messages",
        headers=headers,
        json={"message": "测试", "displayStyle": "FLASH", "publish": True},
    )
    assert invalid_style.status_code == 400

    now = datetime.now(UTC)
    invalid_window = client.post(
        "/api/admin/bot-speech/messages",
        headers=headers,
        json={
            "message": "测试",
            "startsAt": (now + timedelta(hours=2)).isoformat(),
            "endsAt": (now + timedelta(hours=1)).isoformat(),
            "publish": True,
        },
    )
    assert invalid_window.status_code == 400

    past_end = client.post(
        "/api/admin/bot-speech/messages",
        headers=headers,
        json={"message": "测试", "endsAt": (now - timedelta(hours=1)).isoformat(), "publish": True},
    )
    assert past_end.status_code == 400
