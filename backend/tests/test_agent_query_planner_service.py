from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from app.core.config import Settings
from app.models.materials import MaterialRecord
from app.services.agent_memory_service import AgentMemoryContext
from app.services.agent_query_planner_service import AgentQueryPlannerService
from app.services.ai_service import AiService
from app.services.material_pdf_evidence_service import MaterialPageEvidence


def _material(
    material_id: int = 101,
    *,
    title: str = "通信原理四年真题解析",
    description: str = "2021-2024 通信原理期末真题和答案解析",
) -> MaterialRecord:
    return MaterialRecord(
        id=material_id,
        title=title,
        description=description,
        tags_json=json.dumps(["通信原理", "真题", "解析"], ensure_ascii=False),
        school="电子科技大学",
        college="信通",
        major="通信工程",
        course_category="MAJOR",
        grade_value="大三",
        download_count=80,
        rating_avg=4.8,
        is_free=True,
    )


def test_query_planner_detects_exam_trend_plan_from_query_and_evidence() -> None:
    planner = AgentQueryPlannerService()
    evidence = [
        MaterialPageEvidence(
            material_id=101,
            title="通信原理四年真题解析",
            page=3,
            text="2024 通信原理计算题常考调制解调。",
            score=42,
            years=("2024",),
            question_types=("计算题",),
            knowledge_signals=("调制", "解调"),
            question_numbers=("第3题",),
            source_type="past_exam",
            score_points=(10,),
            difficulty_signals=("综合", "偏难"),
            visual_signals=("公式", "图示"),
            anchor_terms=("计算题",),
            anchor_text="2024 通信原理计算题常考调制解调。",
        )
    ]
    memory = AgentMemoryContext(
        platform={"pdf_year_signals": [{"value": "2023", "count": 1}]},
        user={"profile": {"major": "通信"}},
    )

    plan = planner.build_plan(
        "通信原理往年题常考什么",
        materials=[_material()],
        pdf_evidence=evidence,
        memory_context=memory,
    )

    assert plan.intent == "exam_trend_analysis"
    assert plan.confidence >= 0.8
    assert plan.course_terms == ("通信原理",)
    assert "past_exam" in plan.resource_types
    assert plan.years == ("2024", "2023")
    assert "read_relevant_pdf_pages" in plan.evidence_tasks
    assert "aggregate_question_type_signals" in plan.evidence_tasks
    assert "aggregate_score_point_signals" in plan.evidence_tasks
    assert "aggregate_difficulty_signals" in plan.evidence_tasks
    assert "preserve_formula_or_visual_page_refs" in plan.evidence_tasks
    assert "cite_anchor_snippets" in plan.evidence_tasks
    assert "cite_question_numbers" in plan.evidence_tasks
    assert "personalize_with_current_user_memory" in plan.evidence_tasks
    assert any("分值结构" in item and "公式/图表页提示" in item for item in plan.response_guidance)


def test_query_planner_detects_esd_exam_style_plan() -> None:
    plan = AgentQueryPlannerService().build_plan(
        "ESD 考题风格帮我分析一下",
        materials=[
            _material(
                201,
                title="ESD-电子系统设计-2021年真题及答案",
                description="电子系统设计样卷答案和期末考题整理",
            )
        ],
        pdf_evidence=[],
        memory_context=None,
    )

    assert plan.intent == "exam_trend_analysis"
    assert plan.course_terms == ("电子系统设计",)
    assert "past_exam" in plan.resource_types
    assert any(term.lower() == "esd" for term in plan.search_terms)
    assert any("出题风格" in item for item in plan.response_guidance)


def test_query_planner_detects_exam_analysis_focus_dimensions() -> None:
    evidence = [
        MaterialPageEvidence(
            material_id=101,
            title="通信原理四年真题解析",
            page=3,
            text="2024 通信原理计算题常考调制解调。",
            score=42,
            years=("2024",),
            question_types=("计算题",),
            knowledge_signals=("调制", "解调"),
            score_points=(10,),
            difficulty_signals=("综合", "偏难"),
            visual_signals=("公式",),
            source_type="past_exam",
        )
    ]

    plan = AgentQueryPlannerService().build_plan(
        "通信原理近几年分值结构、难度变化和高频知识点怎么分布？",
        materials=[_material()],
        pdf_evidence=evidence,
        memory_context=None,
    )
    payload = plan.to_prompt_payload()

    assert plan.intent == "exam_trend_analysis"
    assert payload["exam_analysis_focus"]["modes"] == [
        "year_trend",
        "knowledge_distribution",
        "score_distribution",
        "difficulty_trend",
    ]
    assert "aggregate_knowledge_signals" in plan.evidence_tasks
    assert "aggregate_score_point_signals" in plan.evidence_tasks
    assert "aggregate_difficulty_signals" in plan.evidence_tasks
    assert "adapt_to_exam_analysis_focus" in plan.evidence_tasks
    assert any("exam_analysis_focus" in item for item in plan.response_guidance)


def test_query_planner_detects_study_plan_without_extra_io() -> None:
    plan = AgentQueryPlannerService().build_plan(
        "我两周后考试，目标85分，每天2小时，调制和误码率很薄弱，应该怎么复习通信原理？",
        materials=[_material()],
        pdf_evidence=[],
        memory_context=None,
    )

    assert plan.intent == "study_plan"
    assert plan.course_terms == ("通信原理",)
    assert plan.study_constraints == {
        "time_horizon": "两周",
        "days_until_exam": 14,
        "target_score": 85,
        "daily_available_hours": 2.0,
        "weak_points": ["调制", "误码率"],
    }
    assert plan.to_prompt_payload()["study_constraints"]["days_until_exam"] == 14
    assert "choose_study_sequence" in plan.evidence_tasks
    assert "adapt_to_user_profile" in plan.evidence_tasks
    assert any("study_constraints" in item for item in plan.response_guidance)


def test_query_planner_detects_learning_preferences_without_extra_io() -> None:
    plan = AgentQueryPlannerService().build_plan(
        "我基础差，想考前速成，多刷真题，但要一步步讲清楚，通信原理怎么复习？",
        materials=[_material()],
        pdf_evidence=[],
        memory_context=None,
    )
    payload = plan.to_prompt_payload()

    assert plan.intent == "study_plan"
    assert plan.learning_preferences == {
        "modes": ["foundation_first", "crash_course", "practice_first", "explanation_first"],
        "labels": ["补基础优先", "考前冲刺", "刷题优先", "详细解析"],
        "guidance": [
            "先补课程框架、核心概念和基础例题，再进入真题训练。",
            "优先抓高频题型、分值高的考点和可快速复盘的资料页。",
            "按题型刷真题或练习，再回查不会的知识点和解析页。",
            "优先选择带答案、解析和步骤的资料，按概念、公式、步骤拆开讲。",
        ],
        "matched_terms": ["基础差", "速成", "考前", "真题", "一步步", "讲清楚"],
    }
    assert payload["learning_preferences"]["modes"] == [
        "foundation_first",
        "crash_course",
        "practice_first",
        "explanation_first",
    ]
    assert "adapt_to_learning_preferences" in plan.evidence_tasks
    assert any("learning_preferences" in item for item in plan.response_guidance)


def test_query_planner_extracts_problem_context_without_extra_io() -> None:
    evidence = [
        MaterialPageEvidence(
            material_id=101,
            title="通信原理四年真题解析",
            page=3,
            text="2024 通信原理第3题公式推导与调制计算。",
            score=42,
            question_numbers=("第3题",),
            knowledge_signals=("调制",),
        )
    ]

    plan = AgentQueryPlannerService().build_plan(
        "通信原理第3题公式推导看不懂，调制怎么做",
        materials=[_material()],
        pdf_evidence=evidence,
        memory_context=None,
    )

    assert plan.intent == "problem_tutoring"
    assert plan.problem_context == {
        "focus_areas": ["概念理解", "公式推导", "计算步骤"],
        "question_numbers": ["第3题"],
        "knowledge_points": ["调制"],
    }
    payload = plan.to_prompt_payload()
    assert payload["problem_context"]["focus_areas"] == ["概念理解", "公式推导", "计算步骤"]
    assert "identify_problem_focus" in plan.evidence_tasks
    assert "explain_step_by_step" in plan.evidence_tasks
    assert "adapt_tutoring_to_problem_context" in plan.evidence_tasks
    assert "track_mentioned_question_numbers" in plan.evidence_tasks
    assert any("problem_context" in item for item in plan.response_guidance)


def test_query_planner_detects_material_fit_assessment() -> None:
    evidence = [
        MaterialPageEvidence(
            material_id=101,
            title="通信原理四年真题解析",
            page=3,
            text="2024 通信原理第3题计算题考调制解调。",
            score=42,
            question_types=("计算题",),
            knowledge_signals=("调制", "解调"),
            source_type="past_exam",
            difficulty_signals=("综合",),
        )
    ]
    memory = AgentMemoryContext(platform={}, user={"profile": {"major": "通信"}})

    plan = AgentQueryPlannerService().build_plan(
        "这份通信原理真题适合我现在看吗",
        materials=[_material()],
        pdf_evidence=evidence,
        memory_context=memory,
    )

    assert plan.intent == "material_fit_assessment"
    assert plan.course_terms == ("通信原理",)
    assert "past_exam" in plan.resource_types
    assert "read_relevant_pdf_pages" in plan.evidence_tasks
    assert "assess_material_fit" in plan.evidence_tasks
    assert "rank_by_quality_and_risk" in plan.evidence_tasks
    assert "personalize_with_current_user_memory" in plan.evidence_tasks
    assert any("适合用户当前阶段" in item for item in plan.response_guidance)


def test_query_planner_detects_multi_material_exam_scope_without_extra_io() -> None:
    evidence = [
        MaterialPageEvidence(
            material_id=101,
            title="通信原理四年真题解析",
            page=3,
            text="2024 通信原理计算题常考调制解调。",
            score=42,
            question_types=("计算题",),
            source_type="past_exam",
        ),
        MaterialPageEvidence(
            material_id=202,
            title="通信原理六年期末题",
            page=5,
            text="2023 通信原理简答题常考系统框图。",
            score=35,
            question_types=("简答题",),
            source_type="past_exam",
        ),
    ]

    plan = AgentQueryPlannerService().build_plan(
        "帮我分析这几份通信原理真题的关键题型",
        materials=[_material(101), _material(202, title="通信原理六年期末题")],
        pdf_evidence=evidence,
        memory_context=None,
    )
    payload = plan.to_prompt_payload()

    assert plan.intent == "exam_trend_analysis"
    assert payload["material_scope"] == {
        "mode": "multi_material",
        "candidate_material_count": 2,
        "pdf_evidence_material_count": 2,
    }
    assert "compare_across_materials" in plan.evidence_tasks
    assert "aggregate_cross_material_question_types" in plan.evidence_tasks
    assert "cite_each_material_sources" in plan.evidence_tasks
    assert any("跨资料共同题型" in item for item in plan.response_guidance)


def test_ai_prompt_receives_query_plan(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    settings = Settings(
        ai_agent_provider="openai-compatible",
        ai_agent_base_url="https://example.test/v1",
        ai_agent_api_key="test-key",
        ai_agent_model="demo-model",
        ai_agent_dynamic_tools_enabled=False,
    )
    monkeypatch.setattr("app.services.ai_service.get_settings", lambda: settings)

    service = AiService(
        read_repo=None,
        material_repo=None,
        query_planner_service=AgentQueryPlannerService(),
    )  # type: ignore[arg-type]
    monkeypatch.setattr(service, "_rank_materials", lambda session, query, filters: [_material()])

    def fake_call_agent_model(settings: Settings, system_prompt: str, user_prompt: dict[str, Any]) -> str:
        captured["system_prompt"] = system_prompt
        captured["user_prompt"] = user_prompt
        return json.dumps(
            {
                "answer": "已按检索计划分析通信原理往年题。",
                "recommendations": [{"material_id": 101, "reason": "匹配 exam_trend_analysis"}],
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

    assert "query_plan" in captured["user_prompt"]
    assert captured["user_prompt"]["query_plan"]["intent"] == "exam_trend_analysis"
    assert "aggregate_year_signals" in captured["user_prompt"]["query_plan"]["evidence_tasks"]
    assert "query_plan" in captured["system_prompt"]
    assert body["answer"] == (
        "已按检索计划分析通信原理往年题。 "
        "说明：当前没有可用 PDF 页级证据，这里仅基于候选资料元数据和可见记忆信号给出保守建议。"
    )
