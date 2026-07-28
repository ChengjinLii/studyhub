from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.deps import get_ai_service
from app.services.auth_service import AuthService
from tests.support import build_auth_headers, seed_read_users


class _SuccessfulAiService:
    @staticmethod
    def memory_cookie_name() -> str:
        return "studyhub_ai_memory"

    @staticmethod
    def resolve_personal_memory_enabled(_cookie_value: str | None) -> bool:
        return True

    @staticmethod
    def recommend(
        _session,
        _payload,
        *,
        current_user_id: int | None,
        current_user_role_mask: int,
        personal_memory_enabled: bool,
        stage_callback,
    ) -> dict[str, object]:
        assert current_user_id == 3
        assert current_user_role_mask == 8
        assert personal_memory_enabled is True
        stage_callback("检索资料中")
        return {
            "output": '<json>{"answer":"## 两周计划\\n\\n1. 先搭框架。"}</json>',
            "recommendations": [],
        }


class _FailingAiService(_SuccessfulAiService):
    @staticmethod
    def recommend(*_args, **_kwargs) -> dict[str, object]:
        raise RuntimeError("provider token=private-secret must not leave the server")


def test_ai_stream_emits_stage_markdown_delta_and_result(
    client: TestClient,
    auth_service: AuthService,
) -> None:
    seed_read_users(auth_service)
    client.app.dependency_overrides[get_ai_service] = _SuccessfulAiService
    try:
        response = client.post(
            "/api/ai-recommendations/stream",
            headers=build_auth_headers(3, 8),
            json={"query": "两周后考通信原理，怎么复习？"},
        )
    finally:
        client.app.dependency_overrides.pop(get_ai_service, None)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache, no-transform"
    assert response.headers["x-accel-buffering"] == "no"
    assert "event: stage" in response.text
    assert "检索资料中" in response.text
    assert "event: delta" in response.text
    assert "## 两周计划" in response.text
    assert "event: result" in response.text


def test_ai_stream_redacts_internal_failure(
    client: TestClient,
    auth_service: AuthService,
) -> None:
    seed_read_users(auth_service)
    client.app.dependency_overrides[get_ai_service] = _FailingAiService
    try:
        response = client.post(
            "/api/ai-recommendations/stream",
            headers=build_auth_headers(3, 8),
            json={"query": "测试异常脱敏"},
        )
    finally:
        client.app.dependency_overrides.pop(get_ai_service, None)

    assert response.status_code == 200
    assert "event: error" in response.text
    assert "AI_STREAM_FAILED" in response.text
    assert "StudyHub 学习辅导暂时无法回答" in response.text
    assert "private-secret" not in response.text
