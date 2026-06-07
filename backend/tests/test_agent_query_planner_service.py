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
    assert "cite_question_numbers" in plan.evidence_tasks
    assert "personalize_with_current_user_memory" in plan.evidence_tasks


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


def test_ai_prompt_receives_query_plan(monkeypatch) -> None:
    captured: dict[str, Any] = {}

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
    assert body["answer"] == "已按检索计划分析通信原理往年题。"
