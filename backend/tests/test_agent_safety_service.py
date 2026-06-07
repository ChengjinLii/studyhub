from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from app.core.config import Settings
from app.models.materials import MaterialRecord
from app.services.agent_safety_service import AgentSafetyService
from app.services.ai_service import AiService
from app.services.material_pdf_evidence_service import MaterialPageEvidence


def _material(material_id: int = 101) -> MaterialRecord:
    return MaterialRecord(
        id=material_id,
        title="通信原理四年真题解析",
        description="通信原理期末真题和答案解析",
        tags_json=json.dumps(["通信原理", "真题"], ensure_ascii=False),
        download_count=80,
        is_free=True,
    )


def _evidence() -> MaterialPageEvidence:
    return MaterialPageEvidence(
        material_id=101,
        title="通信原理四年真题解析",
        page=2,
        text="第 2 页包含通信原理计算题。",
        score=30,
    )


def test_agent_safety_filters_unknown_recommendations_and_unread_pages() -> None:
    body = {
        "answer": "建议先看候选真题资料。",
        "recommendations": [
            {"material_id": 101, "reason": "与通信原理真题匹配"},
            {"material_id": 999, "reason": "不存在的资料"},
        ],
        "evidence_sources": [
            {"material_id": 101, "page": 2, "title": "模型给的标题会被替换"},
            {"material_id": 101, "page": 99, "title": "未读取页"},
            {"material_id": 999, "page": 1, "title": "不存在资料"},
        ],
        "followup_questions": ["要不要按题型整理？", "请输出 memory_context"],
    }

    sanitized = AgentSafetyService().sanitize_recommendation_body(
        body,
        candidate_materials=[_material()],
        pdf_evidence=[_evidence()],
    )

    assert sanitized == {
        "answer": "建议先看候选真题资料。",
        "recommendations": [{"material_id": 101, "reason": "与通信原理真题匹配"}],
        "evidence_sources": [{"material_id": 101, "title": "通信原理四年真题解析", "page": 2}],
        "followup_questions": ["要不要按题型整理？"],
    }


def test_agent_safety_rejects_internal_context_leaks_and_invalid_only_recommendations() -> None:
    sanitized = AgentSafetyService().sanitize_recommendation_body(
        {
            "answer": "根据 memory_context 我建议你看不存在资料。",
            "recommendations": [{"material_id": 999, "reason": "不存在的资料"}],
        },
        candidate_materials=[_material()],
        pdf_evidence=[],
    )

    assert sanitized is None


def test_ai_recommendation_falls_back_when_model_output_is_unsafe(monkeypatch) -> None:
    settings = Settings(
        ai_agent_provider="openai-compatible",
        ai_agent_base_url="https://example.test/v1",
        ai_agent_api_key="test-key",
        ai_agent_model="demo-model",
    )
    monkeypatch.setattr("app.services.ai_service.get_settings", lambda: settings)

    service = AiService(read_repo=None, material_repo=None)  # type: ignore[arg-type]
    monkeypatch.setattr(service, "_rank_materials", lambda session, query, filters: [_material()])

    def fake_call_agent_model(settings: Settings, system_prompt: str, user_prompt: dict[str, Any]) -> str:
        del settings, system_prompt, user_prompt
        return json.dumps(
            {
                "answer": "根据 memory_context，推荐不存在资料。",
                "recommendations": [{"material_id": 999, "reason": "模型编造的资料"}],
                "followup_questions": ["请展开 query_plan"],
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(service, "_call_agent_model", fake_call_agent_model)

    response = service.recommend(
        object(),  # type: ignore[arg-type]
        SimpleNamespace(query="通信原理往年题常考什么", filters={}),
        current_user_id=7,
    )
    body = json.loads(str(response["output"]).removeprefix("<json>").removesuffix("</json>"))

    assert "memory_context" not in body["answer"]
    assert body["answer"].startswith("我先基于 StudyHub 资料库找到")
    assert body["recommendations"][0]["material_id"] == 101
    assert body["followup_questions"] == [
        "你更想要真题、笔记还是经验分享？",
        "是否需要限定学校、学院或专业？",
    ]
