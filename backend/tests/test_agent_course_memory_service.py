from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from app.core.config import Settings
from app.models.materials import MaterialRecord
from app.services.agent_course_memory_service import AgentCourseMemoryService
from app.services.agent_memory_service import AgentMemoryContext
from app.services.agent_query_planner_service import AgentQueryPlan
from app.services.ai_service import AiService
from app.services.material_pdf_evidence_service import MaterialPageEvidence


def _material(
    material_id: int = 101,
    *,
    title: str = "通信原理四年真题解析",
    downloads: int = 80,
) -> MaterialRecord:
    return MaterialRecord(
        id=material_id,
        title=title,
        description="2021-2024 通信原理期末真题和答案解析",
        tags_json=json.dumps(["通信原理", "真题", "解析"], ensure_ascii=False),
        school="电子科技大学",
        college="信通",
        major="通信工程",
        course_category="MAJOR",
        grade_value="大三",
        download_count=downloads,
        rating_avg=4.8,
        is_free=True,
    )


def _evidence() -> MaterialPageEvidence:
    return MaterialPageEvidence(
        material_id=101,
        title="通信原理四年真题解析",
        page=3,
        text="2024 通信原理第3题计算题考调制解调。",
        score=42,
        years=("2024",),
        question_types=("计算题",),
        knowledge_signals=("调制", "解调"),
        chapter_signals=("第2章 调制解调",),
        question_numbers=("第3题",),
        source_type="past_exam",
        score_points=(10,),
        difficulty_signals=("综合", "偏难"),
        visual_signals=("公式", "图示"),
        anchor_terms=("第3题", "计算题"),
        anchor_text="2024 通信原理第3题计算题考调制解调。",
    )


def test_course_memory_card_summarizes_current_request_collective_signals() -> None:
    plan = AgentQueryPlan(
        intent="exam_trend_analysis",
        confidence=0.9,
        course_terms=("通信原理",),
        resource_types=("past_exam",),
        years=("2023",),
        search_terms=("通信原理", "真题"),
        evidence_tasks=("aggregate_year_signals",),
        response_guidance=("优先输出常考题型",),
    )
    memory = AgentMemoryContext(
        platform={"pdf_year_signals": [{"value": "2022", "count": 1}]},
        user={"profile": {"major": "通信"}},
    )

    card = AgentCourseMemoryService().build_card(
        materials=[_material(), _material(102, title="通信原理期末速成", downloads=20)],
        pdf_evidence=[_evidence()],
        memory_context=memory,
        query_plan=plan,
    )

    assert card is not None
    payload = card.to_prompt_payload()
    assert payload["course"] == "通信原理"
    assert payload["version"].startswith("ephemeral-v1-")
    assert len(payload["version_fingerprint"]) == 16
    assert payload["version"].endswith(payload["version_fingerprint"][:12])
    assert payload["version_basis"]["schema"] == "course-memory-card-v1"
    assert payload["version_basis"]["material_ids"] == [101, 102]
    assert payload["version_basis"]["evidence_refs"][0] == {
        "material_id": 101,
        "page": 3,
        "years": ["2024"],
        "question_types": ["计算题"],
        "chapter_signals": ["第2章 调制解调"],
        "question_numbers": ["第3题"],
        "source_type": "past_exam",
        "score_points": [10],
        "difficulty_signals": ["综合", "偏难"],
        "visual_signals": ["公式", "图示"],
        "anchor_terms": ["第3题", "计算题"],
        "anchor_text": "2024 通信原理第3题计算题考调制解调。",
    }
    assert payload["version_basis"]["query_plan"]["intent"] == "exam_trend_analysis"
    version_basis_text = json.dumps(payload["version_basis"], ensure_ascii=False).lower()
    assert "user" not in version_basis_text
    assert "profile" not in version_basis_text
    assert payload["evidence_coverage"] == {
        "candidate_material_count": 2,
        "pdf_evidence_page_count": 1,
        "pdf_evidence_material_count": 1,
        "year_signal_count": 3,
        "question_number_signal_count": 1,
        "source_types": ["past_exam"],
    }
    assert payload["confidence_assessment"] == {
        "level": "medium",
        "signals": ["年份信号覆盖较多"],
        "limitations": ["PDF 证据主要来自单份资料", "题型信号有限"],
    }
    assert payload["years"] == ["2023", "2024", "2022"]
    assert payload["question_type_distribution"] == [{"value": "计算题", "count": 1}]
    assert payload["knowledge_signals"] == [{"value": "调制", "count": 1}, {"value": "解调", "count": 1}]
    assert payload["chapter_distribution"] == [{"value": "第2章 调制解调", "count": 1}]
    assert payload["score_point_distribution"] == [{"value": "10", "count": 1}]
    assert payload["difficulty_distribution"] == [{"value": "综合", "count": 1}, {"value": "偏难", "count": 1}]
    assert payload["visual_signal_distribution"] == [{"value": "公式", "count": 1}, {"value": "图示", "count": 1}]
    assert payload["source_type_distribution"] == [{"value": "past_exam", "count": 1}]
    assert payload["yearly_question_type_matrix"] == [
        {
            "year": "2024",
            "question_types": [{"value": "计算题", "count": 1}],
            "knowledge_signals": [{"value": "调制", "count": 1}, {"value": "解调", "count": 1}],
            "question_numbers": ["第3题"],
            "page_references": [{"material_id": 101, "title": "通信原理四年真题解析", "page": 3}],
        }
    ]
    assert payload["page_references"][0]["question_numbers"] == ["第3题"]
    assert payload["page_references"][0]["chapter_signals"] == ["第2章 调制解调"]
    assert payload["page_references"][0]["score_points"] == [10]
    assert payload["page_references"][0]["difficulty_signals"] == ["综合", "偏难"]
    assert payload["page_references"][0]["visual_signals"] == ["公式", "图示"]
    assert payload["page_references"][0]["anchor_terms"] == ["第3题", "计算题"]
    assert payload["page_references"][0]["anchor_text"] == "2024 通信原理第3题计算题考调制解调。"
    assert payload["recommended_sequence"] == ["先看高频题型", "再核对年份趋势", "最后按页码打开真题资料查漏补缺"]
    assert payload["limitations"] == ["该卡片为当前请求的只读临时汇总，尚未持久化为平台正式课程记忆。"]


def test_course_memory_card_includes_collective_strategy_and_experience_signals() -> None:
    plan = AgentQueryPlan(
        intent="exam_trend_analysis",
        confidence=0.9,
        course_terms=("通信原理",),
        resource_types=("past_exam",),
        years=("2024",),
        search_terms=("通信原理", "真题"),
        evidence_tasks=("aggregate_year_signals",),
        response_guidance=("优先输出常考题型",),
    )
    memory = AgentMemoryContext(
        platform={
            "study_strategy_signals": [
                {"value": "先建立知识框架", "count": 2},
                {"value": "刷真题", "count": 2},
            ],
            "experience_materials": [
                {
                    "material_id": 202,
                    "title": "通信原理考前复习经验分享",
                    "tags": ["经验分享", "通信原理"],
                    "study_strategy_signals": ["先建立知识框架", "刷真题"],
                    "quality_signals": ["高评分资料"],
                }
            ],
        },
        user={"profile": {"major": "不应进入课程集体记忆"}},
    )

    card = AgentCourseMemoryService().build_card(
        materials=[_material(), _material(202, title="通信原理考前复习经验分享", downloads=30)],
        pdf_evidence=[_evidence()],
        memory_context=memory,
        query_plan=plan,
    )

    assert card is not None
    payload = card.to_prompt_payload()
    assert payload["study_strategy_distribution"] == [
        {"value": "先建立知识框架", "count": 2},
        {"value": "刷真题", "count": 2},
    ]
    assert payload["experience_materials"] == [
        {
            "material_id": 202,
            "title": "通信原理考前复习经验分享",
            "tags": ["经验分享", "通信原理"],
            "study_strategy_signals": ["先建立知识框架", "刷真题"],
            "quality_signals": ["高评分资料"],
        }
    ]
    assert payload["recommended_sequence"] == [
        "先看高频题型",
        "再核对年份趋势",
        "最后按页码打开真题资料查漏补缺",
        "先建立知识框架",
        "刷真题",
    ]
    assert payload["version_basis"]["strategy_refs"] == ["先建立知识框架", "刷真题"]
    assert payload["version_basis"]["experience_material_ids"] == [202]
    version_basis_text = json.dumps(payload["version_basis"], ensure_ascii=False).lower()
    assert "不应进入课程集体记忆" not in version_basis_text
    assert "profile" not in version_basis_text


def test_course_memory_card_builds_yearly_question_type_matrix() -> None:
    plan = AgentQueryPlan(
        intent="exam_trend_analysis",
        confidence=0.9,
        course_terms=("通信原理",),
        resource_types=("past_exam",),
        years=("2024", "2023"),
        search_terms=("通信原理", "真题"),
        evidence_tasks=("aggregate_year_signals", "aggregate_question_type_signals"),
        response_guidance=("优先输出常考题型",),
    )
    second_evidence = MaterialPageEvidence(
        material_id=202,
        title="通信原理六年期末题",
        page=5,
        text="2023 通信原理第5题简答题考判决。",
        score=35,
        years=("2023",),
        question_types=("简答题",),
        knowledge_signals=("判决",),
        question_numbers=("第5题",),
        source_type="past_exam",
    )

    card = AgentCourseMemoryService().build_card(
        materials=[_material(), _material(202, title="通信原理六年期末题", downloads=30)],
        pdf_evidence=[_evidence(), second_evidence],
        memory_context=AgentMemoryContext(platform={}, user=None),
        query_plan=plan,
    )

    assert card is not None
    assert card.to_prompt_payload()["yearly_question_type_matrix"] == [
        {
            "year": "2024",
            "question_types": [{"value": "计算题", "count": 1}],
            "knowledge_signals": [{"value": "调制", "count": 1}, {"value": "解调", "count": 1}],
            "question_numbers": ["第3题"],
            "page_references": [{"material_id": 101, "title": "通信原理四年真题解析", "page": 3}],
        },
        {
            "year": "2023",
            "question_types": [{"value": "简答题", "count": 1}],
            "knowledge_signals": [{"value": "判决", "count": 1}],
            "question_numbers": ["第5题"],
            "page_references": [{"material_id": 202, "title": "通信原理六年期末题", "page": 5}],
        },
    ]


def test_course_memory_card_version_is_stable_and_changes_with_sources() -> None:
    plan = AgentQueryPlan(
        intent="exam_trend_analysis",
        confidence=0.9,
        course_terms=("通信原理",),
        resource_types=("past_exam",),
        years=("2024",),
        search_terms=("通信原理", "真题"),
        evidence_tasks=("read_relevant_pdf_pages",),
        response_guidance=("优先输出常考题型",),
    )
    memory = AgentMemoryContext(
        platform={"pdf_year_signals": [{"value": "2024", "count": 1}]},
        user={"profile": {"major": "不应进入版本依据"}},
    )
    service = AgentCourseMemoryService()

    first = service.build_card(
        materials=[_material()],
        pdf_evidence=[_evidence()],
        memory_context=memory,
        query_plan=plan,
    )
    second = service.build_card(
        materials=[_material()],
        pdf_evidence=[_evidence()],
        memory_context=memory,
        query_plan=plan,
    )
    changed = service.build_card(
        materials=[_material(), _material(103, title="通信原理补充真题", downloads=10)],
        pdf_evidence=[_evidence()],
        memory_context=memory,
        query_plan=plan,
    )

    assert first is not None
    assert second is not None
    assert changed is not None
    assert first.version_fingerprint == second.version_fingerprint
    assert first.version == second.version
    assert first.version_fingerprint != changed.version_fingerprint
    assert "不应进入版本依据" not in json.dumps(first.version_basis, ensure_ascii=False)


def test_ai_prompt_receives_course_memory_card(monkeypatch) -> None:
    captured: dict[str, Any] = {}
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
        course_memory_service=AgentCourseMemoryService(),
    )  # type: ignore[arg-type]
    monkeypatch.setattr(service, "_rank_materials", lambda session, query, filters: [_material()])

    def fake_call_agent_model(settings: Settings, system_prompt: str, user_prompt: dict[str, Any]) -> str:
        captured["system_prompt"] = system_prompt
        captured["user_prompt"] = user_prompt
        return json.dumps(
            {
                "answer": "已结合课程记忆卡片分析通信原理真题。",
                "recommendations": [{"material_id": 101, "reason": "匹配课程记忆卡片"}],
                "evidence_sources": [{"material_id": 101, "page": 3, "title": "通信原理四年真题解析"}],
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

    assert "course_memory_card" in captured["user_prompt"]
    assert captured["user_prompt"]["course_memory_card"]["course"] == "通信工程"
    assert captured["user_prompt"]["course_memory_card"]["page_references"][0]["page"] == 3
    assert captured["user_prompt"]["course_memory_card"]["evidence_coverage"]["pdf_evidence_page_count"] == 1
    assert captured["user_prompt"]["course_memory_card"]["confidence_assessment"]["level"] == "low"
    assert "course_memory_card" in captured["system_prompt"]
    assert "confidence_assessment" in captured["system_prompt"]
    assert body["answer"] == "已结合课程记忆卡片分析通信原理真题。 来源：《通信原理四年真题解析》第 3 页（第3题）。"
