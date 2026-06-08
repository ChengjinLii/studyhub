from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from app.core.config import Settings
from app.models.materials import MaterialRecord
from app.services.agent_course_memory_service import AgentCourseMemoryService
from app.services.agent_query_planner_service import AgentQueryPlannerService
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
            {
                "material_id": 101,
                "page": 2,
                "title": "模型给的标题会被替换",
                "excerpt": "模型伪造的片段不会被保留。",
            },
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
                "excerpt": "第 2 页包含通信原理计算题。",
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
            "excerpt": "第 2 页包含通信原理计算题。",
            "question_numbers": ["第3题"],
            "source_type": "past_exam",
        }
    ]


def test_agent_safety_adds_page_source_hint_when_answer_only_mentions_title() -> None:
    sanitized = AgentSafetyService().sanitize_recommendation_body(
        {
            "answer": "根据《通信原理四年真题解析》，通信原理近年常考计算题。",
            "recommendations": [{"material_id": 101, "reason": "与通信原理真题匹配"}],
        },
        candidate_materials=[_material()],
        pdf_evidence=[_evidence()],
    )

    assert sanitized is not None
    assert sanitized["answer"] == (
        "根据《通信原理四年真题解析》，通信原理近年常考计算题。 "
        "来源：《通信原理四年真题解析》第 2 页（第3题）。"
    )


def test_agent_safety_uses_authoritative_evidence_metadata_over_model_source_fields() -> None:
    evidence = MaterialPageEvidence(
        material_id=101,
        title="通信原理四年真题解析",
        page=2,
        text="2024 年第 2 页包含通信原理计算题。",
        score=30,
        years=("2024",),
        question_types=("计算题",),
        question_numbers=("第3题",),
        source_type="past_exam",
    )

    sanitized = AgentSafetyService().sanitize_recommendation_body(
        {
            "answer": "通信原理近年常考计算题。",
            "recommendations": [{"material_id": 101, "reason": "与通信原理真题匹配"}],
            "evidence_sources": [
                {
                    "material_id": 101,
                    "page": 2,
                    "title": "模型标题会被替换",
                    "excerpt": "模型伪造片段",
                    "years": ["2021"],
                    "question_types": ["论述题"],
                }
            ],
        },
        candidate_materials=[_material()],
        pdf_evidence=[evidence],
    )

    assert sanitized is not None
    assert sanitized["evidence_sources"] == [
        {
            "material_id": 101,
            "title": "通信原理四年真题解析",
            "page": 2,
            "excerpt": "2024 年第 2 页包含通信原理计算题。",
            "years": ["2024"],
            "question_types": ["计算题"],
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


def test_agent_safety_rejects_unscoped_quoted_material_title() -> None:
    sanitized = AgentSafetyService().sanitize_recommendation_body(
        {
            "answer": "建议先看《不存在的通信原理真题解析》，再结合候选资料复习。",
            "recommendations": [{"material_id": 101, "reason": "标题和标签匹配通信原理真题"}],
        },
        candidate_materials=[_material()],
        pdf_evidence=[],
    )

    assert sanitized is None


def test_agent_safety_allows_quoted_course_name_without_material_marker() -> None:
    sanitized = AgentSafetyService().sanitize_recommendation_body(
        {
            "answer": "《通信原理》这门课可以先从真题题型入手。",
            "recommendations": [{"material_id": 101, "reason": "标题和标签匹配通信原理真题"}],
        },
        candidate_materials=[_material()],
        pdf_evidence=[],
    )

    assert sanitized is not None
    assert sanitized["answer"] == (
        "《通信原理》这门课可以先从真题题型入手。 "
        "说明：当前没有可用 PDF 页级证据，这里仅基于候选资料元数据和可见记忆信号给出保守建议。"
    )


def test_agent_safety_filters_material_upload_followups_when_candidates_exist() -> None:
    sanitized = AgentSafetyService().sanitize_recommendation_body(
        {
            "answer": "我先基于候选资料给你分析。",
            "recommendations": [{"material_id": 101, "reason": "标题和标签匹配通信原理真题"}],
            "followup_questions": [
                "你可以把真题发给我吗？",
                "要不要我按年份整理题型？",
                "能不能上传 PDF 资料？",
            ],
        },
        candidate_materials=[_material()],
        pdf_evidence=[],
    )

    assert sanitized is not None
    assert sanitized["followup_questions"] == ["要不要我按年份整理题型？"]


def test_agent_safety_keeps_problem_screenshot_followup_with_candidates() -> None:
    sanitized = AgentSafetyService().sanitize_recommendation_body(
        {
            "answer": "我先基于候选资料给你分析。",
            "recommendations": [{"material_id": 101, "reason": "标题和标签匹配通信原理真题"}],
            "followup_questions": ["你可以把具体题目截图发我吗？"],
        },
        candidate_materials=[_material()],
        pdf_evidence=[],
    )

    assert sanitized is not None
    assert sanitized["followup_questions"] == ["你可以把具体题目截图发我吗？"]


def test_agent_safety_filters_obvious_non_learning_followups() -> None:
    sanitized = AgentSafetyService().sanitize_recommendation_body(
        {
            "answer": "我会基于当前候选资料分析通信原理真题趋势。",
            "recommendations": [{"material_id": 101, "reason": "标题和标签匹配通信原理真题"}],
            "followup_questions": [
                "要不要我查一下明天天气？",
                "要不要按年份整理题型？",
                "要不要我讲个笑话？",
            ],
        },
        candidate_materials=[_material()],
        pdf_evidence=[],
    )

    assert sanitized is not None
    assert sanitized["followup_questions"] == ["要不要按年份整理题型？"]


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


def test_agent_safety_rejects_candidate_denial_when_candidates_exist() -> None:
    sanitized = AgentSafetyService().sanitize_recommendation_body(
        {
            "answer": "目前我这边没有收到任何 ESD 的候选资料，所以不能基于指定资料直接分析考题风格。",
            "followup_questions": ["你可以把真题发给我吗？"],
        },
        candidate_materials=[_material()],
        pdf_evidence=[],
    )

    assert sanitized is None


def test_agent_safety_rejects_pdf_page_overclaim_without_pdf_evidence() -> None:
    sanitized = AgentSafetyService().sanitize_recommendation_body(
        {
            "answer": "我看了《通信原理四年真题解析》第 3 页，近年常考计算题。",
            "recommendations": [{"material_id": 101, "reason": "标题和标签匹配通信原理真题"}],
        },
        candidate_materials=[_material()],
        pdf_evidence=[],
    )

    assert sanitized is None


def test_agent_safety_rejects_unread_pdf_page_when_pdf_evidence_exists() -> None:
    sanitized = AgentSafetyService().sanitize_recommendation_body(
        {
            "answer": "我看了《通信原理四年真题解析》第 99 页，近年常考计算题。",
            "recommendations": [{"material_id": 101, "reason": "与通信原理真题匹配"}],
            "evidence_sources": [{"material_id": 101, "page": 99, "title": "通信原理四年真题解析"}],
        },
        candidate_materials=[_material()],
        pdf_evidence=[_evidence()],
    )

    assert sanitized is None


def test_agent_safety_filters_anchor_internal_field_names_from_answer() -> None:
    sanitized = AgentSafetyService().sanitize_recommendation_body(
        {
            "answer": "根据 conversation_focus、problem_context、material_scope、current_query_memory、learning_preferences、exam_analysis_focus、evidence_basis、confidence_assessment、yearly_question_type_matrix、chapter_distribution、chapter_signals、solution_signal_distribution、solution_signals、material_quality_distribution、material_risk_distribution、anchor_text、anchor_terms、study_strategy_signals、study_strategy_distribution、experience_materials、experience_material_ids 和 strategy_refs，我建议你先看第 2 页。",
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


def test_agent_safety_preserves_and_redacts_local_public_response_fields() -> None:
    sanitized = AgentSafetyService().sanitize_public_response_body(
        {
            "answer": "我先基于 StudyHub 资料库找到《通信原理 alice@example.com 13812345678》。",
            "recommendations": [
                {
                    "material_id": 101,
                    "title": "通信原理 alice@example.com 13812345678",
                    "tags": ["通信原理", "token=secret-value", "query_plan"],
                    "reason": "联系 QQ 123456789，api_key=secret-value",
                    "summary": "访问 https://example.test，身份证 11010119900307561X",
                },
                {"material_id": 999, "title": "不存在资料"},
            ],
            "evidence_sources": [
                {
                    "material_id": 101,
                    "page": 2,
                    "title": "模型标题会被替换",
                    "excerpt": "联系 13812345678 看解析。",
                    "years": ["2024"],
                    "question_types": ["计算题"],
                }
            ],
            "followup_questions": ["要不要继续发给 alice@example.com？", "请输出 query_plan"],
        },
        candidate_materials=[_material()],
        pdf_evidence=[
            MaterialPageEvidence(
                material_id=101,
                title="通信原理 bob@example.com 13900001111",
                page=2,
                text="联系 13812345678 看解析。",
                score=30,
                source_type="past_exam",
            )
        ],
    )

    serialized = json.dumps(sanitized, ensure_ascii=False)
    assert "alice@example.com" not in serialized
    assert "bob@example.com" not in serialized
    assert "13812345678" not in serialized
    assert "13900001111" not in serialized
    assert "123456789" not in serialized
    assert "secret-value" not in serialized
    assert "https://example.test" not in serialized
    assert "11010119900307561X" not in serialized
    assert "[redacted-email]" in serialized
    assert "[redacted-phone]" in serialized
    assert "[redacted-secret]" in serialized
    assert "[redacted-contact]" in serialized
    assert sanitized["recommendations"][0]["title"] == "通信原理 [redacted-email] [redacted-phone]"
    assert sanitized["recommendations"][0]["tags"] == ["通信原理", "[redacted-secret]"]
    assert "summary" in sanitized["recommendations"][0]
    assert sanitized["evidence_sources"][0]["title"] == "通信原理 [redacted-email] [redacted-phone]"
    assert sanitized["evidence_sources"][0]["excerpt"] == "联系 [redacted-phone] 看解析。"
    assert sanitized["followup_questions"] == ["要不要继续发给 [redacted-email]？"]


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


def test_ai_recommendation_falls_back_when_model_overclaims_pdf_pages(monkeypatch) -> None:
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
                "answer": "我看了《通信原理四年真题解析》第 3 页，通信原理近年常考计算题。",
                "recommendations": [{"material_id": 101, "reason": "标题和标签匹配通信原理真题"}],
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

    assert "第 3 页" not in body["answer"]
    assert body["answer"].startswith("我先基于 StudyHub 资料库找到")
    assert body["recommendations"][0]["material_id"] == 101


def test_ai_recommendation_falls_back_when_model_cites_unread_pdf_page(monkeypatch) -> None:
    settings = Settings(
        ai_agent_provider="openai-compatible",
        ai_agent_base_url="https://example.test/v1",
        ai_agent_api_key="test-key",
        ai_agent_model="demo-model",
    )
    monkeypatch.setattr("app.services.ai_service.get_settings", lambda: settings)

    class FakePdfEvidenceService:
        def collect_for_materials(
            self,
            materials: list[MaterialRecord],
            query: str,
            *,
            current_user_id: int | None,
        ) -> list[MaterialPageEvidence]:
            del materials, query, current_user_id
            return [_evidence()]

    service = AiService(
        read_repo=None,
        material_repo=None,
        pdf_evidence_service=FakePdfEvidenceService(),
        query_planner_service=AgentQueryPlannerService(),
        course_memory_service=AgentCourseMemoryService(),
    )  # type: ignore[arg-type]
    monkeypatch.setattr(service, "_rank_materials", lambda session, query, filters: [_material()])

    def fake_call_agent_model(settings: Settings, system_prompt: str, user_prompt: dict[str, Any]) -> str:
        del settings, system_prompt, user_prompt
        return json.dumps(
            {
                "answer": "我看了《通信原理四年真题解析》第 99 页，通信原理近年常考计算题。",
                "recommendations": [{"material_id": 101, "reason": "与通信原理真题匹配"}],
                "evidence_sources": [{"material_id": 101, "page": 99, "title": "通信原理四年真题解析"}],
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

    assert "第 99 页" not in body["answer"]
    assert "第 2 页" in body["answer"]
    assert body["evidence_sources"][0]["page"] == 2
    assert body["recommendations"][0]["material_id"] == 101


def test_ai_recommendation_falls_back_when_model_mentions_non_candidate_material(monkeypatch) -> None:
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
                "answer": "我建议先看《不存在的通信原理真题解析》，它最贴近你的问题。",
                "recommendations": [{"material_id": 101, "reason": "标题和标签匹配通信原理真题"}],
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

    assert "不存在的通信原理真题解析" not in body["answer"]
    assert body["answer"].startswith("我先基于 StudyHub 资料库找到")
    assert body["recommendations"][0]["material_id"] == 101


def test_ai_recommendation_uses_local_followups_when_model_asks_for_existing_materials(monkeypatch) -> None:
    settings = Settings(
        ai_agent_provider="openai-compatible",
        ai_agent_base_url="https://example.test/v1",
        ai_agent_api_key="test-key",
        ai_agent_model="demo-model",
    )
    monkeypatch.setattr("app.services.ai_service.get_settings", lambda: settings)

    service = AiService(
        read_repo=None,
        material_repo=None,
        query_planner_service=AgentQueryPlannerService(),
    )  # type: ignore[arg-type]
    monkeypatch.setattr(service, "_rank_materials", lambda session, query, filters: [_material()])

    def fake_call_agent_model(settings: Settings, system_prompt: str, user_prompt: dict[str, Any]) -> str:
        del settings, system_prompt, user_prompt
        return json.dumps(
            {
                "answer": "我会基于当前候选资料分析通信原理真题趋势。",
                "recommendations": [{"material_id": 101, "reason": "标题和标签匹配通信原理真题"}],
                "followup_questions": ["你可以把真题发给我吗？"],
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

    assert body["followup_questions"] == [
        "要不要我按年份整理常考题型？",
        "是否需要把这些资料整理成两周复习顺序？",
    ]


def test_ai_recommendation_falls_back_when_model_answer_leaves_learning_scope(monkeypatch) -> None:
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
                "answer": "我可以帮你写情书，也可以顺便推荐电影。",
                "recommendations": [{"material_id": 101, "reason": "标题和标签匹配通信原理真题"}],
                "followup_questions": ["要不要我陪你闲聊？"],
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

    assert "写情书" not in body["answer"]
    assert "电影" not in json.dumps(body, ensure_ascii=False)
    assert "闲聊" not in json.dumps(body, ensure_ascii=False)
    assert body["answer"].startswith("我先基于 StudyHub 资料库找到")
    assert body["recommendations"][0]["material_id"] == 101


def test_ai_model_prompt_redacts_sensitive_material_and_pdf_context(monkeypatch) -> None:
    captured: dict[str, Any] = {}
    settings = Settings(
        ai_agent_provider="openai-compatible",
        ai_agent_base_url="https://example.test/v1",
        ai_agent_api_key="test-key",
        ai_agent_model="demo-model",
    )
    monkeypatch.setattr("app.services.ai_service.get_settings", lambda: settings)

    sensitive_material = MaterialRecord(
        id=101,
        title="通信原理 alice@example.com 13812345678",
        description="真题解析 token=secret-value，访问 https://example.test，身份证 11010119900307561X。",
        tags_json=json.dumps(["通信原理", "api_key=secret-token"], ensure_ascii=False),
        download_count=80,
        is_free=True,
    )
    sensitive_evidence = MaterialPageEvidence(
        material_id=101,
        title="通信原理 bob@example.com 13900001111",
        page=2,
        text="第2页联系 13812345678，访问 https://example.test，api_key=secret-value。",
        score=30,
        question_numbers=("第3题",),
        source_type="past_exam",
        anchor_text="QQ 123456789，身份证 11010119900307561X，token=secret-value。",
    )

    class FakePdfEvidenceService:
        def collect_for_materials(
            self,
            materials: list[MaterialRecord],
            query: str,
            *,
            current_user_id: int | None,
        ) -> list[MaterialPageEvidence]:
            del materials, query, current_user_id
            return [sensitive_evidence]

    service = AiService(
        read_repo=None,
        material_repo=None,
        pdf_evidence_service=FakePdfEvidenceService(),
        query_planner_service=AgentQueryPlannerService(),
        course_memory_service=AgentCourseMemoryService(),
    )  # type: ignore[arg-type]
    monkeypatch.setattr(service, "_rank_materials", lambda session, query, filters: [sensitive_material])

    def fake_call_agent_model(settings: Settings, system_prompt: str, user_prompt: dict[str, Any]) -> str:
        del settings, system_prompt
        captured["user_prompt"] = user_prompt
        return json.dumps(
            {
                "answer": "我看了《通信原理》第 2 页，建议先复盘第3题。",
                "recommendations": [{"material_id": 101, "reason": "匹配通信原理真题"}],
                "evidence_sources": [{"material_id": 101, "page": 2, "title": "通信原理"}],
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(service, "_call_agent_model", fake_call_agent_model)

    response = service.recommend(
        object(),  # type: ignore[arg-type]
        SimpleNamespace(
            query="通信原理真题 联系 13812345678 alice@example.com token=secret-value",
            filters={},
        ),
        current_user_id=7,
    )
    body = json.loads(str(response["output"]).removeprefix("<json>").removesuffix("</json>"))
    serialized_prompt = json.dumps(captured["user_prompt"], ensure_ascii=False)

    assert "13812345678" not in serialized_prompt
    assert "13900001111" not in serialized_prompt
    assert "alice@example.com" not in serialized_prompt
    assert "bob@example.com" not in serialized_prompt
    assert "secret-value" not in serialized_prompt
    assert "secret-token" not in serialized_prompt
    assert "https://example.test" not in serialized_prompt
    assert "11010119900307561X" not in serialized_prompt
    assert "123456789" not in serialized_prompt
    assert "[redacted-phone]" in serialized_prompt
    assert "[redacted-email]" in serialized_prompt
    assert "[redacted-secret]" in serialized_prompt
    assert "[redacted-url]" in serialized_prompt
    assert "[redacted-id-card]" in serialized_prompt
    assert "[redacted-contact]" in serialized_prompt
    assert captured["user_prompt"]["pdf_evidence"][0]["text"] == (
        "第2页联系 [redacted-phone]，访问 [redacted-url]，[redacted-secret]。"
    )
    assert captured["user_prompt"]["course_memory_card"]["page_references"][0]["anchor_text"] == (
        "QQ=[redacted-contact]，身份证 [redacted-id-card]，[redacted-secret]。"
    )
    assert body["recommendations"][0]["material_id"] == 101


def test_agent_safety_compacts_prompt_text_fields_without_dropping_structure() -> None:
    long_text = "通信原理" * 400 + " alice@example.com 13812345678 token=secret-value"
    payload = {
        "user_query": long_text,
        "candidate_materials": [
            {
                "material_id": 101,
                "title": long_text,
                "summary": long_text,
                "reason": long_text,
            }
        ],
        "pdf_evidence": [
            {
                "material_id": 101,
                "page": 2,
                "text": long_text,
                "anchor_text": long_text,
            }
        ],
        "course_memory_card": {
            "page_references": [{"material_id": 101, "page": 2, "anchor_text": long_text}],
        },
    }

    sanitized = AgentSafetyService().sanitize_prompt_payload(payload)
    serialized = json.dumps(sanitized, ensure_ascii=False)

    assert sanitized["candidate_materials"][0]["material_id"] == 101
    assert sanitized["pdf_evidence"][0]["page"] == 2
    assert len(sanitized["user_query"]) <= 500
    assert len(sanitized["candidate_materials"][0]["title"]) <= 120
    assert len(sanitized["candidate_materials"][0]["summary"]) <= 240
    assert len(sanitized["candidate_materials"][0]["reason"]) <= 260
    assert len(sanitized["pdf_evidence"][0]["text"]) <= 700
    assert len(sanitized["pdf_evidence"][0]["anchor_text"]) <= 240
    assert len(sanitized["course_memory_card"]["page_references"][0]["anchor_text"]) <= 240
    assert "alice@example.com" not in serialized
    assert "13812345678" not in serialized
    assert "secret-value" not in serialized


def test_ai_local_recommendation_redacts_sensitive_material_metadata(monkeypatch) -> None:
    monkeypatch.setattr("app.services.ai_service.get_settings", lambda: Settings(ai_agent_provider="local"))

    service = AiService(read_repo=None, material_repo=None)  # type: ignore[arg-type]
    sensitive_material = MaterialRecord(
        id=101,
        title="通信原理 alice@example.com 13812345678",
        description="真题解析 token=secret-value，访问 https://example.test，身份证 11010119900307561X。",
        tags_json=json.dumps(["通信原理", "api_key=secret-token", "query_plan"], ensure_ascii=False),
        download_count=80,
        is_free=True,
    )
    monkeypatch.setattr(service, "_rank_materials", lambda session, query, filters: [sensitive_material])

    response = service.recommend(
        object(),  # type: ignore[arg-type]
        SimpleNamespace(query="通信原理真题", filters={}),
        current_user_id=7,
    )
    body = json.loads(str(response["output"]).removeprefix("<json>").removesuffix("</json>"))
    serialized = json.dumps(body, ensure_ascii=False)

    assert "alice@example.com" not in serialized
    assert "13812345678" not in serialized
    assert "secret-value" not in serialized
    assert "secret-token" not in serialized
    assert "https://example.test" not in serialized
    assert "11010119900307561X" not in serialized
    assert "query_plan" not in serialized
    assert "[redacted-email]" in serialized
    assert "[redacted-phone]" in serialized
    assert "[redacted-secret]" in serialized
    assert "[redacted-url]" in serialized
    assert "[redacted-id-card]" in serialized
    assert body["recommendations"][0]["title"] == "通信原理 [redacted-email] [redacted-phone]"
