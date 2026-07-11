from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from app.core.config import Settings
from app.models.materials import MaterialRecord
from app.services.agent_orchestrator_service import AgentOrchestrationPlan, AgentOrchestratorService
from app.services.ai_service import AiService
from app.services.material_pdf_evidence_service import MaterialPageEvidence


def _settings(**overrides: Any) -> Settings:
    return Settings(
        ai_agent_provider="openai-compatible",
        ai_agent_base_url="https://example.test/v1",
        ai_agent_api_key="test-key",
        ai_agent_model="hermes-test",
        ai_agent_dynamic_tools_enabled=True,
        ai_agent_tool_max_rounds=4,
        ai_agent_tool_max_calls=6,
        ai_agent_tool_max_candidates=12,
        ai_agent_tool_max_evidence_pages=10,
        **overrides,
    )


def _material(material_id: int = 801) -> MaterialRecord:
    return MaterialRecord(
        id=material_id,
        title="现代控制理论公式推导与例题",
        description="覆盖状态空间、能控性和稳定性推导。",
        tags_json=json.dumps(["现代控制", "公式推导"], ensure_ascii=False),
        school="电子科技大学",
        college="自动化",
        major="现代控制理论",
        course_category="MAJOR",
        grade_value="大三",
        file_type="pdf",
        file_storage_key="materials/801/control.pdf",
        is_free=True,
        status="VISIBLE",
        review_status="APPROVED",
        download_count=20,
        rating_avg=4.5,
        rating_count=4,
    )


def _evidence(page: int = 20) -> MaterialPageEvidence:
    return MaterialPageEvidence(
        material_id=801,
        title="现代控制理论公式推导与例题",
        page=page,
        text="第 20 页给出能控性矩阵的推导步骤和例题。",
        score=90,
        years=(),
        question_types=("计算题",),
        knowledge_signals=("能控性",),
        chapter_signals=("状态空间",),
        solution_signals=("解题步骤",),
        question_numbers=("例题2",),
        source_type="lecture_notes",
        score_points=(),
        difficulty_signals=("综合",),
        visual_signals=("公式",),
        anchor_terms=("能控性",),
        anchor_text="能控性矩阵的推导步骤",
    )


def test_dynamic_agent_can_answer_open_learning_task_without_search(monkeypatch) -> None:
    settings = _settings()
    monkeypatch.setattr("app.services.ai_service.get_settings", lambda: settings)
    service = AiService(read_repo=None, material_repo=None)  # type: ignore[arg-type]
    monkeypatch.setattr(
        service,
        "_rank_materials",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("direct explanation should not search")),
    )
    monkeypatch.setattr(
        service,
        "_call_agent_model",
        lambda *args, **kwargs: json.dumps(
            {
                "mode": "final",
                "answer": "## 拉普拉斯变换直观解释\n\n它把微分运算转换为代数运算。",
                "followup_questions": ["用一个二阶微分方程演示完整变换过程"],
            },
            ensure_ascii=False,
        ),
    )

    response = service.recommend(
        object(),  # type: ignore[arg-type]
        SimpleNamespace(query="直观解释拉普拉斯变换", filters={}, imageAttachments=[]),
        current_user_id=7,
    )
    body = json.loads(str(response["output"]).removeprefix("<json>").removesuffix("</json>"))

    assert body["answer"].startswith("## 拉普拉斯变换直观解释")
    assert "PDF 页级证据" not in body["answer"]
    assert "recommendations" not in body


def test_dynamic_agent_searches_then_requests_specific_pdf_page(monkeypatch) -> None:
    settings = _settings(ai_agent_pdf_extract_max_pages=80)
    monkeypatch.setattr("app.services.ai_service.get_settings", lambda: settings)
    captured: dict[str, Any] = {}
    stages: list[str] = []

    class FakePdfEvidenceService:
        def collect_for_materials(self, materials: list[MaterialRecord], query: str, **kwargs: Any) -> list[MaterialPageEvidence]:
            captured["evidence_material_ids"] = [int(item.id) for item in materials]
            captured["evidence_query"] = query
            captured["evidence_kwargs"] = kwargs
            return [_evidence()]

    service = AiService(
        read_repo=None,
        material_repo=None,
        pdf_evidence_service=FakePdfEvidenceService(),  # type: ignore[arg-type]
    )  # type: ignore[arg-type]
    monkeypatch.setattr(service, "_rank_materials", lambda session, query, filters: [_material()])
    responses = iter(
        [
            {
                "mode": "tools",
                "actions": [
                    {
                        "name": "search_materials",
                        "arguments": {"query": "现代控制 能控性 公式推导", "limit": 5},
                    }
                ],
            },
            {
                "mode": "tools",
                "actions": [
                    {
                        "name": "read_pdf_evidence",
                        "arguments": {
                            "material_ids": [801],
                            "query": "能控性矩阵 推导",
                            "page_numbers": [20],
                            "max_pages": 3,
                        },
                    }
                ],
            },
            {
                "mode": "final",
                "answer": "## 能控性矩阵怎么推\n\n《现代控制理论公式推导与例题》第 20 页给出了推导入口。",
                "recommendations": [
                    {"material_id": 999, "reason": "不存在"},
                    {"material_id": 801, "reason": "第 20 页直接覆盖能控性矩阵推导"},
                ],
                "evidence_sources": [
                    {"material_id": 801, "page": 20, "title": "现代控制理论公式推导与例题"}
                ],
                "followup_questions": ["按第 20 页例题拆解每一步计算"],
            },
        ]
    )
    monkeypatch.setattr(
        service,
        "_call_agent_model",
        lambda *args, **kwargs: json.dumps(next(responses), ensure_ascii=False),
    )

    response = service.recommend(
        object(),  # type: ignore[arg-type]
        SimpleNamespace(query="给我推导一下能控性矩阵，必要时看看资料后面的例题", filters={}, imageAttachments=[]),
        current_user_id=7,
        stage_callback=stages.append,
    )
    body = json.loads(str(response["output"]).removeprefix("<json>").removesuffix("</json>"))

    assert captured["evidence_material_ids"] == [801]
    assert captured["evidence_kwargs"]["force"] is True
    assert captured["evidence_kwargs"]["page_numbers"] == {20}
    assert "第 20 页" in body["answer"]
    assert [item["material_id"] for item in body["recommendations"]] == [801]
    assert body["evidence_sources"][0]["page"] == 20
    assert any("现代控制" in stage for stage in stages)
    assert any("第 20 页" in stage for stage in stages)


def test_orchestrator_accepts_open_task_and_strategy_labels() -> None:
    fallback = AgentOrchestrationPlan(
        scope="learning",
        route="fallback",
        should_search=False,
        use_context=False,
        search_query="",
        intent="fallback",
    )
    plan = AgentOrchestratorService().parse(
        {
            "scope": "learning",
            "route": "derive_formula_then_design_mock_exam",
            "intent": "公式推导与模拟考试设计",
            "should_search": False,
            "use_context": True,
        },
        fallback=fallback,
    )

    assert plan.route == "derive_formula_then_design_mock_exam"
    assert plan.intent == "公式推导与模拟考试设计"
    assert plan.use_context is True
