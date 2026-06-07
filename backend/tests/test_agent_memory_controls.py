from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from app.core.db import session_scope
from app.models.materials import MaterialRecord
from app.repos.material_repo import MaterialRepository
from app.services.ai_service import AiService
from tests.support import build_auth_headers, seed_read_users


def _seed_memory_material(user_id: int = 1) -> None:
    material_repo = MaterialRepository()
    with session_scope() as session:
        material_repo.save_material(
            session,
            MaterialRecord(
                id=770,
                source="local",
                uploader_id=2,
                uploader_username="baishan",
                uploader_nickname="白山",
                title="通信原理真题解析记忆预览",
                description="通信原理期末真题、计算题和调制解调解析",
                file_type="pdf",
                price=0,
                is_free=True,
                school="电子科技大学",
                college="信通",
                major="通信工程",
                course_category="MAJOR",
                grade_value="大三",
                tags_json=json.dumps(["通信原理", "真题", "解析"], ensure_ascii=False),
                status="VISIBLE",
                review_status="APPROVED",
                download_count=12,
                rating_avg=4.9,
                like_count=3,
            ),
        )
        material_repo.add_favorite(session, material_id=770, user_id=user_id)


def test_ai_memory_preview_shows_current_user_derived_memory(client, auth_service) -> None:
    seed_read_users(auth_service)
    _seed_memory_material(user_id=1)

    response = client.get("/api/ai/memory", headers=build_auth_headers(1, 1))

    assert response.status_code == 200
    data = response.json()["data"]
    serialized = json.dumps(data, ensure_ascii=False)
    assert data["personalMemoryEnabled"] is True
    assert data["mode"] == "read_only_derived"
    assert data["personalMemory"]["profile"] == {
        "school": "电子科技大学",
        "college": "信通",
        "major": "通信",
        "grade_stages": "大三",
    }
    assert data["personalMemory"]["candidate_interactions"][0] == {
        "material_id": 770,
        "title": "通信原理真题解析记忆预览",
        "signals": ["favorited"],
    }
    assert data["controls"]["canDisableCurrentBrowser"] is True
    assert data["controls"]["canDeletePersistedMemory"] is False
    assert "alice@example.com" not in serialized
    assert "Alice Chen" not in serialized


def test_ai_memory_preference_cookie_disables_preview(client, auth_service) -> None:
    seed_read_users(auth_service)
    _seed_memory_material(user_id=1)
    headers = build_auth_headers(1, 1)

    preference_response = client.put("/api/ai/memory-preferences", headers=headers, json={"enabled": False})
    preview_response = client.get("/api/ai/memory", headers=headers)

    assert preference_response.status_code == 200
    assert any(
        "studyhub_ai_memory=disabled" in header and "HttpOnly" in header
        for header in preference_response.headers.get_list("set-cookie")
    )
    data = preview_response.json()["data"]
    assert data["personalMemoryEnabled"] is False
    assert data["disabledReason"] == "user_preference"
    assert data["personalMemory"] is None


def test_ai_recommendation_skips_memory_collection_when_personal_memory_disabled(monkeypatch) -> None:
    material = MaterialRecord(
        id=771,
        title="通信原理真题解析",
        description="通信原理期末真题和答案解析",
        tags_json=json.dumps(["通信原理", "真题"], ensure_ascii=False),
        is_free=True,
        download_count=5,
    )

    class FailingMemoryService:
        def collect(self, *args: Any, **kwargs: Any) -> None:
            raise AssertionError("memory collection should be skipped")

    service = AiService(read_repo=None, material_repo=None, memory_service=FailingMemoryService())  # type: ignore[arg-type]
    monkeypatch.setattr(service, "_rank_materials", lambda session, query, filters: [material])

    captured: dict[str, Any] = {}

    def fake_generate(
        query: str,
        materials: list[MaterialRecord],
        *,
        pdf_evidence: list[Any],
        memory_context: Any,
        query_plan: Any,
        course_memory_card: Any,
    ) -> None:
        del query, materials, pdf_evidence, query_plan, course_memory_card
        captured["memory_context"] = memory_context
        return None

    monkeypatch.setattr(service, "_generate_agent_recommendation", fake_generate)

    response = service.recommend(
        object(),  # type: ignore[arg-type]
        SimpleNamespace(query="通信原理往年题常考什么", filters={}),
        current_user_id=1,
        personal_memory_enabled=False,
    )
    body = json.loads(str(response["output"]).removeprefix("<json>").removesuffix("</json>"))

    assert captured["memory_context"] is None
    assert body["recommendations"][0]["material_id"] == 771
