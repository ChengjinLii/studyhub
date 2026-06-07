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
        question_numbers=("第3题",),
        source_type="past_exam",
        score_points=(10,),
        difficulty_signals=("综合", "偏难"),
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
        "question_numbers": ["第3题"],
        "source_type": "past_exam",
        "score_points": [10],
        "difficulty_signals": ["综合", "偏难"],
    }
    assert payload["version_basis"]["query_plan"]["intent"] == "exam_trend_analysis"
    version_basis_text = json.dumps(payload["version_basis"], ensure_ascii=False).lower()
    assert "user" not in version_basis_text
    assert "profile" not in version_basis_text
    assert payload["years"] == ["2023", "2024", "2022"]
    assert payload["question_type_distribution"] == [{"value": "计算题", "count": 1}]
    assert payload["knowledge_signals"] == [{"value": "调制", "count": 1}, {"value": "解调", "count": 1}]
    assert payload["score_point_distribution"] == [{"value": "10", "count": 1}]
    assert payload["difficulty_distribution"] == [{"value": "综合", "count": 1}, {"value": "偏难", "count": 1}]
    assert payload["source_type_distribution"] == [{"value": "past_exam", "count": 1}]
    assert payload["page_references"][0]["question_numbers"] == ["第3题"]
    assert payload["page_references"][0]["score_points"] == [10]
    assert payload["page_references"][0]["difficulty_signals"] == ["综合", "偏难"]
    assert payload["recommended_sequence"] == ["先看高频题型", "再核对年份趋势", "最后按页码打开真题资料查漏补缺"]
    assert payload["limitations"] == ["该卡片为当前请求的只读临时汇总，尚未持久化为平台正式课程记忆。"]


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
    assert "course_memory_card" in captured["system_prompt"]
    assert body["answer"] == "已结合课程记忆卡片分析通信原理真题。 来源：《通信原理四年真题解析》第 3 页（第3题）。"
