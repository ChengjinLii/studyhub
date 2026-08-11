from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from app.core.config import Settings
from app.models.materials import MaterialRecord
from app.services.agent_orchestrator_service import AgentOrchestrationPlan, AgentOrchestratorService
from app.services.ai_service import AiService
from app.services.agent_tool_loop_service import (
    AGENT_TOOL_LOOP_CONTINUE_INSTRUCTION,
    AGENT_TOOL_LOOP_FORCE_FINAL_INSTRUCTION,
    AgentToolLoopService,
)
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


def test_dynamic_agent_preserves_model_extracted_context_across_rewritten_searches(monkeypatch) -> None:
    settings = _settings(ai_agent_tool_max_search_calls=3)
    monkeypatch.setattr("app.services.ai_service.get_settings", lambda: settings)
    service = AiService(read_repo=None, material_repo=None)  # type: ignore[arg-type]
    searched_queries: list[str] = []
    model_payloads: list[dict[str, Any]] = []

    def fake_rank(session, query, filters):
        del session, filters
        searched_queries.append(query)
        return [_material(801 if len(searched_queries) == 1 else 802)]

    responses = iter(
        [
            {
                "mode": "tools",
                "task_context": {
                    "course_terms": ["ESD", "电子系统设计"],
                    "exam_goal": "两周后完成期末复习",
                    "time_budget": {"days_until_exam": 14, "daily_hours": 2},
                    "resource_types": ["样卷", "解析"],
                    "constraints": ["基础一般"],
                },
                "actions": [{"name": "search_materials", "arguments": {"query": "ESD 期末 样卷", "limit": 4}}],
            },
            {
                "mode": "tools",
                "actions": [
                    {
                        "name": "search_materials",
                        "arguments": {"query": "电子系统设计 样卷 答案解析", "limit": 4},
                    }
                ],
            },
            {
                "mode": "final",
                "answer": "## ESD 复习建议\n\n先建立知识框架，再使用样卷查漏补缺。",
                "recommendations": [{"material_id": 801, "reason": "与期末目标匹配"}],
                "followup_questions": ["把两周任务细化到每天两小时"],
            },
        ]
    )

    def fake_model(settings, system_prompt, payload):
        del settings, system_prompt
        model_payloads.append(payload)
        return json.dumps(next(responses), ensure_ascii=False)

    monkeypatch.setattr(service, "_rank_materials", fake_rank)
    monkeypatch.setattr(service, "_call_agent_model", fake_model)

    response = service.recommend(
        object(),  # type: ignore[arg-type]
        SimpleNamespace(query="两周后考 ESD，基础一般，怎么复习？", filters={}, imageAttachments=[]),
        current_user_id=7,
    )
    body = json.loads(str(response["output"]).removeprefix("<json>").removesuffix("</json>"))

    assert searched_queries == ["ESD 期末 样卷", "电子系统设计 样卷 答案解析"]
    assert model_payloads[1]["task_context"] == {
        "course_terms": ["ESD", "电子系统设计"],
        "exam_goal": "两周后完成期末复习",
        "time_budget": {"days_until_exam": 14.0, "daily_hours": 2.0},
        "resource_types": ["样卷", "解析"],
        "constraints": ["基础一般"],
    }
    assert model_payloads[2]["search_history"][0]["query"] == "ESD 期末 样卷"
    assert model_payloads[2]["search_history"][1]["query"] == "电子系统设计 样卷 答案解析"
    assert model_payloads[2]["budget"]["remaining_search_calls"] == 1
    assert body["answer"].startswith("## ESD 复习建议")


def test_dynamic_agent_enforces_search_budget_without_reclassifying_task(monkeypatch) -> None:
    settings = _settings(ai_agent_tool_max_search_calls=1)
    monkeypatch.setattr("app.services.ai_service.get_settings", lambda: settings)
    service = AiService(read_repo=None, material_repo=None)  # type: ignore[arg-type]
    searched_queries: list[str] = []
    model_payloads: list[dict[str, Any]] = []
    responses = iter(
        [
            {
                "mode": "tools",
                "task_context": {"course_terms": ["通信原理"], "exam_goal": "期末复习"},
                "actions": [{"name": "search_materials", "arguments": {"query": "通信原理 真题"}}],
            },
            {
                "mode": "tools",
                "actions": [{"name": "search_materials", "arguments": {"query": "CPS 期末解析"}}],
            },
            {
                "mode": "final",
                "answer": "## 通信原理复习\n\n使用当前候选完成第一轮复习。",
                "recommendations": [{"material_id": 801, "reason": "课程匹配"}],
            },
        ]
    )

    monkeypatch.setattr(
        service,
        "_rank_materials",
        lambda session, query, filters: searched_queries.append(query) or [_material()],
    )

    def fake_model(settings, system_prompt, payload):
        del settings, system_prompt
        model_payloads.append(payload)
        return json.dumps(next(responses), ensure_ascii=False)

    monkeypatch.setattr(service, "_call_agent_model", fake_model)
    service.recommend(
        object(),  # type: ignore[arg-type]
        SimpleNamespace(query="两周后考通信原理", filters={}, imageAttachments=[]),
        current_user_id=7,
    )

    assert searched_queries == ["通信原理 真题"]
    exhausted = model_payloads[2]["tool_observations"][-1]
    assert exhausted["result"]["reason"] == "search_budget_exhausted"
    assert model_payloads[2]["task_context"]["course_terms"] == ["通信原理"]


def test_runtime_constraints_are_disabled_by_default() -> None:
    assert Settings(_env_file=None).ai_agent_runtime_constraints_enabled is False


def test_tool_loop_adds_structured_routing_state_only_when_enabled() -> None:
    service = AgentToolLoopService()
    arguments = {
        "query": "通信原理真题怎么复习",
        "conversation_context": "",
        "platform_term_glossary": {},
        "has_image": False,
        "observations": [
            {
                "tool": "search_materials",
                "result": {"candidates": [{"material_id": 801}]},
            },
            {
                "tool": "read_pdf_evidence",
                "result": {"evidence": [{"material_id": 801, "page": 20}]},
            },
        ],
        "task_context": {},
        "search_history": [],
        "remaining_rounds": 2,
        "remaining_tool_calls": 3,
        "remaining_search_calls": 1,
        "remaining_candidate_slots": 5,
    }

    legacy = service.build_request(**arguments)
    constrained = service.build_request(**arguments, runtime_constraints_enabled=True)
    forced = service.build_request(**arguments, force_final=True)

    assert "routing_state" not in legacy
    assert legacy["instruction"] == AGENT_TOOL_LOOP_CONTINUE_INSTRUCTION
    assert forced["instruction"] == AGENT_TOOL_LOOP_FORCE_FINAL_INSTRUCTION
    assert constrained["routing_state"] == {
        "version": "studyhub.router.state.v1",
        "must_finish_without_tools": False,
        "budget_phase": "tools_available",
        "evidence_phase": "available",
        "candidate_phase": "search_results_only",
        "memory_phase": "not_loaded",
    }


def test_tool_loop_routing_state_matches_production_tool_result_shapes() -> None:
    service = AgentToolLoopService()
    payload = service.build_request(
        query="通信原理错题怎么复习",
        conversation_context="",
        platform_term_glossary={},
        has_image=False,
        observations=[
            {
                "tool": "search_materials",
                "result": {"candidates": [{"id": 801}]},
            },
            {
                "tool": "inspect_materials",
                "result": {"materials": [{"id": 801}]},
            },
            {
                "tool": "read_pdf_evidence",
                "result": {"evidence": [{"material_id": 801, "page": 20}]},
            },
            {
                "tool": "read_memory",
                "result": {"focus": "薄弱点", "memory": {}},
            },
        ],
        task_context={},
        search_history=[],
        remaining_rounds=2,
        remaining_tool_calls=3,
        remaining_search_calls=1,
        remaining_candidate_slots=5,
        runtime_constraints_enabled=True,
    )

    assert payload["routing_state"] == {
        "version": "studyhub.router.state.v1",
        "must_finish_without_tools": False,
        "budget_phase": "tools_available",
        "evidence_phase": "available",
        "candidate_phase": "details_observed",
        "memory_phase": "loaded",
    }


def test_tool_loop_repairs_only_explicit_allowlisted_read_action() -> None:
    service = AgentToolLoopService()
    malformed = (
        '{"mode":"tools","progress":"检索中","actions":['
        '{"name":"search_materials","arguments":{"query":"通信原理 真题","limit":5}}'
    )

    assert service.parse_model_output(malformed, repair=False) is None
    repaired = service.parse_model_output(malformed, repair=True)

    assert repaired is not None
    assert repaired.mode == "tools"
    assert repaired.actions[0].name == "search_materials"
    assert repaired.actions[0].arguments == {"query": "通信原理 真题", "limit": 5}


def test_tool_loop_rejects_malformed_unsupported_action() -> None:
    service = AgentToolLoopService()
    malformed = (
        '{"mode":"tools","actions":['
        '{"name":"delete_database","arguments":{"material_ids":[801]}}'
    )

    assert service.parse_model_output(malformed, repair=True) is None


def test_tool_loop_never_recovers_tool_from_malformed_final_payload() -> None:
    service = AgentToolLoopService()
    malformed = (
        '{"mode":"final","metadata":{"name":"search_materials"},'
        '"actions":[{"name":"search_materials","arguments":{"query":"不应执行"}}],'
        '"answer":"安全回答"'
    )

    repaired = service.parse_model_output(malformed, repair=True)

    assert repaired is not None
    assert repaired.mode == "final"
    assert repaired.actions == ()


def test_dynamic_agent_uses_guarded_parser_only_when_flag_enabled(monkeypatch) -> None:
    settings = _settings(ai_agent_runtime_constraints_enabled=True)
    monkeypatch.setattr("app.services.ai_service.get_settings", lambda: settings)
    service = AiService(read_repo=None, material_repo=None)  # type: ignore[arg-type]
    searched_queries: list[str] = []
    model_payloads: list[dict[str, Any]] = []
    responses = iter(
        [
            (
                '{"mode":"tools","actions":['
                '{"name":"search_materials","arguments":{"query":"通信原理 真题","limit":4}}'
            ),
            json.dumps(
                {
                    "mode": "final",
                    "answer": "## 通信原理复习\n\n优先用真题建立题型地图。",
                    "recommendations": [{"material_id": 801, "reason": "课程匹配"}],
                },
                ensure_ascii=False,
            ),
        ]
    )
    monkeypatch.setattr(
        service,
        "_rank_materials",
        lambda session, query, filters: searched_queries.append(query) or [_material()],
    )

    def fake_model(settings, system_prompt, payload):
        del settings, system_prompt
        model_payloads.append(payload)
        return next(responses)

    monkeypatch.setattr(service, "_call_agent_model", fake_model)

    response = service.recommend(
        object(),  # type: ignore[arg-type]
        SimpleNamespace(query="通信原理怎么复习", filters={}, imageAttachments=[]),
        current_user_id=7,
    )
    body = json.loads(str(response["output"]).removeprefix("<json>").removesuffix("</json>"))

    assert searched_queries == ["通信原理 真题"]
    assert model_payloads[0]["routing_state"]["candidate_phase"] == "not_observed"
    assert model_payloads[1]["routing_state"]["candidate_phase"] == "search_results_only"
    assert body["answer"].startswith("## 通信原理复习")
