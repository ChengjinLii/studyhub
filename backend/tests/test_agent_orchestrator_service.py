from app.services.agent_orchestrator_service import (
    AgentOrchestrationPlan,
    AgentOrchestratorService,
)


def _fallback() -> AgentOrchestrationPlan:
    return AgentOrchestrationPlan(
        scope="learning",
        route="new_material_search",
        should_search=True,
        use_context=False,
        search_query="原始问题",
        intent="general_learning_support",
        source="fallback",
    )


def test_model_orchestrator_parses_complete_semantic_plan() -> None:
    service = AgentOrchestratorService()

    plan = service.parse(
        {
            "scope": "learning",
            "route": "revise_study_plan",
            "should_search": False,
            "use_context": True,
            "search_query": "不应保留",
            "intent": "study_plan",
            "confidence": 0.93,
            "course_terms": ["通信原理"],
            "resource_types": ["真题", "讲义"],
            "study_constraints": {"days_until_exam": 14, "daily_available_hours": 2},
            "learning_preferences": {"modes": ["foundation_first", "practice_first"]},
            "evidence_tasks": ["沿用上一轮资料", "按薄弱点排期"],
            "response_guidance": ["按第 1-14 天输出"],
            "followup_guidance": ["细化前七天", "整理刷题顺序"],
            "reason": "用户正在细化上一轮计划",
        },
        fallback=_fallback(),
    )

    assert plan.source == "model"
    assert plan.intent == "study_plan"
    assert plan.use_context is True
    assert plan.should_search is False
    assert plan.search_query == ""
    assert plan.study_constraints["days_until_exam"] == 14
    assert plan.followup_guidance == ("细化前七天", "整理刷题顺序")


def test_model_orchestrator_keeps_user_text_for_semantic_judgment() -> None:
    request = AgentOrchestratorService().build_request(
        "需要我帮你分析真题吗？",
        context_query="上一轮讨论通信原理",
        has_image=False,
    )

    assert request["current_user_query"] == "需要我帮你分析真题吗？"
    assert request["user_query"] == "需要我帮你分析真题吗？"
    assert "允许" not in request["current_user_query"]


def test_model_orchestrator_restricts_scope_but_accepts_open_task_labels() -> None:
    fallback = _fallback()
    plan = AgentOrchestratorService().parse(
        {
            "scope": "unsafe-scope",
            "route": "delete_database",
            "intent": "invent_material",
            "should_search": True,
            "search_query": "通信原理 真题",
        },
        fallback=fallback,
    )

    assert plan.scope == fallback.scope
    assert plan.route == "delete_database"
    assert plan.intent == "invent_material"
    assert plan.search_query == "通信原理 真题"
