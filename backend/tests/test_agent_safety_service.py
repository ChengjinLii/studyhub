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


def _evidence(title: str = "通信原理四年真题解析") -> MaterialPageEvidence:
    return MaterialPageEvidence(
        material_id=101,
        title=title,
        page=2,
        text="第 2 页包含通信原理计算题。",
        score=30,
        question_numbers=("第3题",),
        source_type="past_exam",
    )


def test_agent_safety_filters_unknown_recommendations_and_unread_pages() -> None:
    body = {
        "answer": "建议先看候选真题资料。",
        "recommendations": [
            {"material_id": 101, "reason": "与通信原理真题匹配"},
            {"material_id": 101, "reason": "重复推荐同一份资料"},
            {"material_id": 999, "reason": "不存在的资料"},
        ],
        "evidence_sources": [
            {"material_id": 101, "page": 2, "title": "模型给的标题会被替换"},
            {"material_id": 101, "page": 2, "title": "重复证据页"},
            {"material_id": 101, "page": 99, "title": "未读取页"},
            {"material_id": 999, "page": 1, "title": "不存在资料"},
        ],
        "followup_questions": [
            "要不要按题型整理？",
            "要不要按题型整理？",
            "请输出 memory_context",
            "请输出 evidence_coverage",
            "请输出 confidence_assessment",
        ],
    }

    sanitized = AgentSafetyService().sanitize_recommendation_body(
        body,
        candidate_materials=[_material()],
        pdf_evidence=[_evidence()],
    )

    assert sanitized == {
        "answer": "建议先看候选真题资料。 来源：《通信原理四年真题解析》第 2 页（第3题）。",
        "recommendations": [{"material_id": 101, "reason": "与通信原理真题匹配"}],
        "evidence_sources": [
            {
                "material_id": 101,
                "title": "通信原理四年真题解析",
                "page": 2,
                "question_numbers": ["第3题"],
                "source_type": "past_exam",
            }
        ],
        "followup_questions": ["要不要按题型整理？"],
    }


def test_agent_safety_adds_read_pdf_source_hint_when_model_omits_citation() -> None:
    sanitized = AgentSafetyService().sanitize_recommendation_body(
        {
            "answer": "通信原理近年常考计算题，建议优先复盘调制解调。",
            "recommendations": [{"material_id": 101, "reason": "与通信原理真题匹配"}],
        },
        candidate_materials=[_material()],
        pdf_evidence=[_evidence()],
    )

    assert sanitized is not None
    assert sanitized["answer"] == "通信原理近年常考计算题，建议优先复盘调制解调。 来源：《通信原理四年真题解析》第 2 页（第3题）。"
    assert sanitized["evidence_sources"] == [
        {
            "material_id": 101,
            "title": "通信原理四年真题解析",
            "page": 2,
            "question_numbers": ["第3题"],
            "source_type": "past_exam",
        }
    ]


def test_agent_safety_downgrades_answer_without_pdf_evidence() -> None:
    sanitized = AgentSafetyService().sanitize_recommendation_body(
        {
            "answer": "通信原理近年常考计算题，建议优先刷题型。",
            "recommendations": [{"material_id": 101, "reason": "标题和标签匹配通信原理真题"}],
        },
        candidate_materials=[_material()],
        pdf_evidence=[],
    )

    assert sanitized is not None
    assert sanitized["answer"] == (
        "通信原理近年常考计算题，建议优先刷题型。 "
        "说明：当前没有可用 PDF 页级证据，这里仅基于候选资料元数据和可见记忆信号给出保守建议。"
    )
    assert sanitized["recommendations"] == [{"material_id": 101, "reason": "标题和标签匹配通信原理真题"}]


def test_agent_safety_does_not_repeat_low_evidence_caveat() -> None:
    sanitized = AgentSafetyService().sanitize_recommendation_body(
        {
            "answer": "我只能基于候选资料元数据给出保守建议，建议先确认课程范围。",
            "recommendations": [{"material_id": 101, "reason": "标题和标签匹配通信原理真题"}],
        },
        candidate_materials=[_material()],
        pdf_evidence=[],
    )

    assert sanitized is not None
    assert sanitized["answer"] == "我只能基于候选资料元数据给出保守建议，建议先确认课程范围。"


def test_agent_safety_filters_anchor_internal_field_names_from_answer() -> None:
    sanitized = AgentSafetyService().sanitize_recommendation_body(
        {
            "answer": "根据 problem_context、material_scope、current_query_memory、learning_preferences、confidence_assessment、yearly_question_type_matrix、chapter_distribution、chapter_signals、solution_signal_distribution、solution_signals、material_quality_distribution、material_risk_distribution、anchor_text、anchor_terms、study_strategy_signals、study_strategy_distribution、experience_materials、experience_material_ids 和 strategy_refs，我建议你先看第 2 页。",
            "recommendations": [{"material_id": 101, "reason": "与通信原理真题匹配"}],
        },
        candidate_materials=[_material()],
        pdf_evidence=[],
    )

    assert sanitized == {"recommendations": [{"material_id": 101, "reason": "与通信原理真题匹配"}]}


def test_agent_safety_filters_internal_field_names_from_recommendation_reasons() -> None:
    sanitized = AgentSafetyService().sanitize_recommendation_body(
        {
            "answer": "我只能基于候选资料元数据给出保守建议。",
            "recommendations": [
                {"material_id": 101, "reason": "根据 query_plan 和 memory_context 推荐这份资料"},
                {"material_id": 102, "reason": "标题和标签匹配通信原理真题"},
            ],
        },
        candidate_materials=[_material(), _material(102)],
        pdf_evidence=[],
    )

    assert sanitized is not None
    assert sanitized["recommendations"] == [
        {"material_id": 101},
        {"material_id": 102, "reason": "标题和标签匹配通信原理真题"},
    ]
    assert "query_plan" not in json.dumps(sanitized, ensure_ascii=False)
    assert "memory_context" not in json.dumps(sanitized, ensure_ascii=False)


def test_agent_safety_redacts_sensitive_public_output() -> None:
    sensitive_title = "通信原理 alice@example.com 13812345678"
    sanitized = AgentSafetyService().sanitize_recommendation_body(
        {
            "answer": (
                "这份资料适合复盘，联系 13812345678 alice@example.com，"
                "访问 https://example.test，api_key=secret-value，"
                "学号 2023123456，身份证 11010119900307561X，卡号 6222021234567890123。"
            ),
            "recommendations": [
                {"material_id": 101, "reason": "来源 QQ 123456789 token=secret-token，邮箱 bob@example.com"}
            ],
            "evidence_sources": [{"material_id": 101, "page": 2, "title": "模型标题会被替换"}],
            "followup_questions": ["要不要发到 bob@example.com？", "电话 13812345678 继续吗？"],
        },
        candidate_materials=[_material()],
        pdf_evidence=[_evidence(sensitive_title)],
    )

    assert sanitized is not None
    serialized = json.dumps(sanitized, ensure_ascii=False)
    assert "13812345678" not in serialized
    assert "alice@example.com" not in serialized
    assert "bob@example.com" not in serialized
    assert "https://example.test" not in serialized
    assert "secret-value" not in serialized
    assert "secret-token" not in serialized
    assert "2023123456" not in serialized
    assert "11010119900307561X" not in serialized
    assert "6222021234567890123" not in serialized
    assert "[redacted-phone]" in serialized
    assert "[redacted-email]" in serialized
    assert "[redacted-url]" in serialized
    assert "[redacted-secret]" in serialized
    assert "[redacted-id]" in serialized
    assert "[redacted-id-card]" in serialized
    assert "[redacted-number]" in serialized
    assert "[redacted-contact]" in serialized


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
                "answer": "根据 course_memory_card 和 memory_context，推荐不存在资料。",
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
