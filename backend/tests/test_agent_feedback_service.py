from __future__ import annotations

import json

from app.core.config import get_settings
from app.core.db import session_scope
from app.core.observability import get_runtime_metrics
from app.models.materials import MaterialRecord
from app.repos.material_repo import MaterialRepository
from tests.support import build_auth_headers, seed_read_users


def _seed_feedback_materials() -> None:
    material_repo = MaterialRepository()
    with session_scope() as session:
        material_repo.save_material(
            session,
            MaterialRecord(
                id=780,
                source="local",
                uploader_id=2,
                title="通信原理反馈真题解析",
                description="通信原理期末真题与解析",
                file_type="pdf",
                price=0,
                is_free=True,
                school="电子科技大学",
                college="信通",
                major="通信工程",
                tags_json=json.dumps(["通信原理", "真题"], ensure_ascii=False),
                status="VISIBLE",
                review_status="APPROVED",
                download_count=18,
                rating_avg=4.7,
            ),
        )
        material_repo.save_material(
            session,
            MaterialRecord(
                id=781,
                source="local",
                uploader_id=2,
                title="隐藏资料不应进入反馈候选",
                file_type="pdf",
                price=0,
                is_free=True,
                status="HIDDEN",
                download_count=1,
            ),
        )


def test_ai_feedback_builds_redacted_user_and_platform_memory_candidates(client, auth_service) -> None:
    get_runtime_metrics().clear()
    seed_read_users(auth_service)
    _seed_feedback_materials()

    response = client.post(
        "/api/ai/feedback",
        headers=build_auth_headers(1, 1),
        json={
            "hook": "useful",
            "selectedMaterialIds": [780, 781, 999, 780],
            "note": (
                "真题解析有帮助，但我基础差，希望以后多给一步步详细解析和刷题顺序，"
                "联系我 13812345678 alice@example.com api_key=secret-value "
                "https://example.test QQ 123456789 微信 studyhub_user 学号 2023123456 "
                "身份证 11010119900307561X 卡号 6222021234567890123"
            ),
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    serialized = json.dumps(data, ensure_ascii=False)
    assert data["accepted"] is True
    assert data["hook"] == "useful"
    assert data["selectedMaterialIds"] == [780]
    assert data["personalMemoryEnabled"] is True
    assert "13812345678" not in serialized
    assert "alice@example.com" not in serialized
    assert "secret-value" not in serialized
    assert "https://example.test" not in serialized
    assert "123456789" not in serialized
    assert "studyhub_user" not in serialized
    assert "2023123456" not in serialized
    assert "11010119900307561X" not in serialized
    assert "6222021234567890123" not in serialized
    assert "[redacted-phone]" in data["redactedNote"]
    assert "[redacted-email]" in data["redactedNote"]
    assert "[redacted-secret]" in data["redactedNote"]
    assert "[redacted-url]" in data["redactedNote"]
    assert "[redacted-contact]" in data["redactedNote"]
    assert "[redacted-id]" in data["redactedNote"]
    assert "[redacted-id-card]" in data["redactedNote"]
    assert "[redacted-number]" in data["redactedNote"]
    assert [item["scope"] for item in data["memoryCandidates"]] == ["user", "platform"]
    assert data["memoryCandidates"][0]["key"] == "agent_feedback_preference"
    user_memory_value = data["memoryCandidates"][0]["value"]
    assert "用户补充" not in user_memory_value
    assert "[redacted-" not in user_memory_value
    assert "基础差" not in user_memory_value
    assert "反馈信号：有帮助、补基础优先、刷题优先、详细解析。" in user_memory_value
    assert data["memoryCandidates"][0]["derivedSignals"] == {
        "positive_feedback": ["有帮助"],
        "learning_preferences": ["补基础优先", "刷题优先", "详细解析"],
    }
    assert data["memoryCandidates"][0]["selectedMaterialSignals"] == {
        "courses": ["通信原理"],
        "sourceTypes": ["往年真题", "答案解析"],
        "qualitySignals": ["标签较完整", "审核通过", "已有下载反馈"],
        "riskSignals": ["简介较短", "交付信息缺失"],
    }
    assert data["memoryCandidates"][1]["privacy"] == "anonymous_aggregate_candidate"
    assert data["memoryCandidates"][1]["aggregateSignals"] == {
        "positive_feedback": ["有帮助"],
        "learning_preferences": ["补基础优先", "刷题优先", "详细解析"],
    }
    assert data["memoryCandidates"][1]["selectedMaterialSignals"] == data["memoryCandidates"][0]["selectedMaterialSignals"]
    metrics = get_runtime_metrics().render_prometheus(get_settings())
    assert (
        'studyhub_ai_agent_feedback_total{hook="useful",status="accepted",'
        'personal_memory="yes",selected_materials="yes"} 1'
    ) in metrics
    get_runtime_metrics().clear()


def test_ai_feedback_respects_disabled_personal_memory_cookie(client, auth_service) -> None:
    seed_read_users(auth_service)
    _seed_feedback_materials()
    headers = build_auth_headers(1, 1)
    assert client.put("/api/ai/memory-preferences", headers=headers, json={"enabled": False}).status_code == 200

    response = client.post(
        "/api/ai/feedback",
        headers=headers,
        json={"hook": "too_hard", "selectedMaterialIds": [780], "note": "这个计划有点难，基础差，需要一步步讲清楚"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["accepted"] is True
    assert data["personalMemoryEnabled"] is False
    assert [item["scope"] for item in data["memoryCandidates"]] == ["platform"]
    assert data["memoryCandidates"][0]["aggregateSignals"] == {
        "difficulty_feedback": ["偏困难"],
        "learning_preferences": ["补基础优先", "详细解析"],
    }
    assert data["memoryCandidates"][0]["selectedMaterialSignals"]["courses"] == ["通信原理"]


def test_ai_feedback_rejects_unknown_hooks_without_memory_candidates(client, auth_service) -> None:
    get_runtime_metrics().clear()
    seed_read_users(auth_service)
    _seed_feedback_materials()

    response = client.post(
        "/api/ai/feedback",
        headers=build_auth_headers(1, 1),
        json={"hook": "dump_memory_context", "selectedMaterialIds": [780]},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["accepted"] is False
    assert data["reason"] == "invalid_hook"
    assert data["memoryCandidates"] == []
    assert "useful" in data["allowedHooks"]
    metrics = get_runtime_metrics().render_prometheus(get_settings())
    assert (
        'studyhub_ai_agent_feedback_total{hook="dump_memory_context",status="rejected",'
        'personal_memory="yes",selected_materials="yes"} 1'
    ) in metrics
    get_runtime_metrics().clear()
