from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from app.core.config import Settings
from app.core.observability import get_runtime_metrics
from app.models.materials import MaterialRecord
from app.services.agent_course_memory_service import AgentCourseMemoryService
from app.services.agent_memory_service import AgentMemoryContext
from app.services.agent_query_planner_service import AgentQueryPlannerService
from app.services.ai_service import AiService
from app.services.material_pdf_evidence_service import MaterialPageEvidence


def _material(
    material_id: int,
    *,
    title: str,
    description: str,
    downloads: int,
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
        download_count=downloads,
        rating_avg=4.8,
        like_count=12,
        is_free=True,
    )


def _evidence() -> MaterialPageEvidence:
    return MaterialPageEvidence(
        material_id=101,
        title="通信原理四年真题解析",
        page=3,
        text="2024 通信原理第3题计算题考调制、解调和误码率。",
        score=56,
        years=("2024",),
        question_types=("计算题",),
        knowledge_signals=("调制", "解调", "误码率"),
        chapter_signals=("第2章 调制解调",),
        solution_signals=("参考答案", "解题步骤"),
        question_numbers=("第3题",),
        source_type="past_exam",
        score_points=(10,),
        difficulty_signals=("综合", "偏难"),
        visual_signals=("公式", "图示"),
        anchor_terms=("第3题", "计算题"),
        anchor_text="2024 通信原理第3题计算题考调制、解调和误码率。",
    )


def test_agent_ranking_uses_material_quality_as_tie_breaker() -> None:
    high_quality = MaterialRecord(
        id=301,
        title="通信原理真题资料",
        description="通信原理期末真题、详细答案解析、常考题型和复习建议整理",
        tags_json=json.dumps(["通信原理", "真题", "解析"], ensure_ascii=False),
        file_storage_key="materials/high.pdf",
        file_type="pdf",
        preview_status="done",
        review_status="APPROVED",
        copyright_owner="课程组",
        download_count=20,
        like_count=12,
        rating_avg=4.8,
        rating_count=5,
        is_free=True,
    )
    low_quality = MaterialRecord(
        id=302,
        title="通信原理真题资料",
        description="短",
        tags_json=json.dumps(["通信原理"], ensure_ascii=False),
        download_count=90,
        rating_avg=0,
        rating_count=0,
        is_free=True,
    )

    class FakeReadRepo:
        def load_seed(self) -> dict[str, Any]:
            return {}

    class FakeMaterialRepo:
        def ensure_seed_bootstrap(self, session: object, seed: dict[str, Any]) -> None:
            del session, seed

        def list_visible_materials(self, session: object) -> list[MaterialRecord]:
            del session
            return [low_quality, high_quality]

    service = AiService(read_repo=FakeReadRepo(), material_repo=FakeMaterialRepo())  # type: ignore[arg-type]

    ranked = service._rank_materials(object(), "通信原理真题", {})  # type: ignore[arg-type]

    assert [item.id for item in ranked] == [301, 302]


def test_agent_ranking_demotes_high_risk_material_when_relevance_ties() -> None:
    safe_material = MaterialRecord(
        id=303,
        title="通信原理真题资料",
        description="通信原理期末真题、详细答案解析、常考题型和复习建议整理",
        tags_json=json.dumps(["通信原理", "真题", "解析"], ensure_ascii=False),
        file_storage_key="materials/safe.pdf",
        file_type="pdf",
        preview_status="done",
        review_status="APPROVED",
        copyright_owner="课程组",
        download_count=12,
        rating_avg=4.5,
        rating_count=3,
        is_free=True,
    )
    risky_material = MaterialRecord(
        id=304,
        title="通信原理真题资料",
        description="通信原理期末真题、解析和内部泄题资料，联系我买卖答案，原题泄露。",
        tags_json=json.dumps(["通信原理", "真题", "解析"], ensure_ascii=False),
        file_storage_key="materials/risky.pdf",
        file_type="pdf",
        preview_status="done",
        review_status="APPROVED",
        copyright_owner="课程组",
        download_count=200,
        rating_avg=4.9,
        rating_count=20,
        is_free=True,
    )

    class FakeReadRepo:
        def load_seed(self) -> dict[str, Any]:
            return {}

    class FakeMaterialRepo:
        def ensure_seed_bootstrap(self, session: object, seed: dict[str, Any]) -> None:
            del session, seed

        def list_visible_materials(self, session: object) -> list[MaterialRecord]:
            del session
            return [risky_material, safe_material]

    service = AiService(read_repo=FakeReadRepo(), material_repo=FakeMaterialRepo())  # type: ignore[arg-type]

    ranked = service._rank_materials(object(), "通信原理真题", {})  # type: ignore[arg-type]

    assert [item.id for item in ranked] == [303, 304]


def test_agent_ranking_matches_natural_study_search_aliases() -> None:
    exam_material = MaterialRecord(
        id=401,
        title="通信原理期末试卷高频重点题型整理",
        description="包含选择题、计算题和参考答案讲解",
        tags_json=json.dumps(["通信原理", "题型"], ensure_ascii=False),
        download_count=8,
        rating_avg=4.4,
        rating_count=2,
        is_free=True,
    )
    plan_material = MaterialRecord(
        id=402,
        title="通信原理备考计划与冲刺安排",
        description="按两周学习计划整理章节重点和刷题顺序",
        tags_json=json.dumps(["通信原理", "复习"], ensure_ascii=False),
        download_count=5,
        rating_avg=4.2,
        rating_count=2,
        is_free=True,
    )
    generic_material = MaterialRecord(
        id=403,
        title="通信原理课堂资料汇总",
        description="基础课程资料",
        tags_json=json.dumps(["通信原理"], ensure_ascii=False),
        download_count=80,
        rating_avg=4.9,
        rating_count=10,
        is_free=True,
    )

    class FakeReadRepo:
        def load_seed(self) -> dict[str, Any]:
            return {}

    class FakeMaterialRepo:
        def ensure_seed_bootstrap(self, session: object, seed: dict[str, Any]) -> None:
            del session, seed

        def list_visible_materials(self, session: object) -> list[MaterialRecord]:
            del session
            return [generic_material, plan_material, exam_material]

    service = AiService(read_repo=FakeReadRepo(), material_repo=FakeMaterialRepo())  # type: ignore[arg-type]

    exam_ranked = service._rank_materials(object(), "通信原理往年题常考什么", {})  # type: ignore[arg-type]
    plan_ranked = service._rank_materials(object(), "通信原理复习计划", {})  # type: ignore[arg-type]

    assert exam_ranked[0].id == 401
    assert plan_ranked[0].id == 402


def test_agent_ranking_handles_esd_query_with_unloaded_compatibility_columns() -> None:
    esd_material = SimpleNamespace(
        id=501,
        title="ESD-电子系统设计-2021年真题及答案",
        description="电子系统设计样卷答案和期末考题整理",
        school="电子科技大学",
        college="自动化",
        major="电子系统设计",
        course_category="MAJOR",
        grade_value="大三",
        file_type="pdf",
        is_free=True,
        download_count=12,
        rating_avg=4.6,
        rating_count=3,
        like_count=2,
        created_at=None,
    )
    cps_material = SimpleNamespace(
        id=502,
        title="CPS 通信原理四年真题解析",
        description="通信原理期末真题和答案解析",
        school="电子科技大学",
        college="信通",
        major="通信工程",
        course_category="MAJOR",
        grade_value="大三",
        file_type="pdf",
        is_free=True,
        download_count=100,
        rating_avg=4.9,
        rating_count=10,
        like_count=20,
        created_at=None,
    )

    class FakeReadRepo:
        def load_seed(self) -> dict[str, Any]:
            return {}

    class FakeMaterialRepo:
        def ensure_seed_bootstrap(self, session: object, seed: dict[str, Any]) -> None:
            del session, seed

        def list_visible_materials(self, session: object) -> list[Any]:
            del session
            return [cps_material, esd_material]

    service = AiService(read_repo=FakeReadRepo(), material_repo=FakeMaterialRepo())  # type: ignore[arg-type]

    ranked = service._rank_materials(object(), "esd考题风格帮我分析一下", {})  # type: ignore[arg-type]

    assert ranked[0].id == 501
    assert "电子系统设计" in ranked[0].title


def test_agent_followup_context_uses_clean_material_title_for_retrieval_and_plan(monkeypatch) -> None:
    metrics = get_runtime_metrics()
    metrics.clear()
    captured: dict[str, Any] = {}
    settings = Settings(
        ai_agent_provider="openai-compatible",
        ai_agent_base_url="https://example.test/v1",
        ai_agent_api_key="test-key",
        ai_agent_model="demo-model",
    )
    monkeypatch.setattr("app.services.ai_service.get_settings", lambda: settings)
    esd_material = MaterialRecord(
        id=501,
        title="ESD-电子系统设计-2021年真题及答案",
        description="电子系统设计 2021 年真题、样卷答案和期末考题整理",
        tags_json=json.dumps(["电子系统设计", "真题", "答案"], ensure_ascii=False),
        school="电子科技大学",
        college="自动化",
        major="电子系统设计",
        course_category="MAJOR",
        grade_value="大三",
        file_type="pdf",
        is_free=True,
        download_count=30,
        rating_avg=4.6,
        rating_count=4,
    )
    service = AiService(
        read_repo=None,
        material_repo=None,
        query_planner_service=AgentQueryPlannerService(),
        course_memory_service=AgentCourseMemoryService(),
    )  # type: ignore[arg-type]

    def fake_rank_materials(session: object, query: str, filters: dict[str, Any]) -> list[MaterialRecord]:
        del session, filters
        captured["rank_query"] = query
        return [esd_material]

    def fake_call_agent_model(settings: Settings, system_prompt: str, user_prompt: dict[str, Any]) -> str:
        del settings, system_prompt
        captured["user_prompt"] = user_prompt
        return json.dumps(
            {
                "answer": "我会基于《ESD-电子系统设计-2021年真题及答案》分析电子系统设计的考题风格。",
                "recommendations": [{"material_id": 501, "reason": "上下文课程和资料标题匹配"}],
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(service, "_rank_materials", fake_rank_materials)
    monkeypatch.setattr(service, "_call_agent_model", fake_call_agent_model)

    context_query = (
        "早期上下文摘要：课程/关键词：电子系统设计。"
        "曾推荐资料：ESD-电子系统设计-2021年真题及答案 用户：后续讨论 助手：后续讨论"
    )
    response = service.recommend(
        object(),  # type: ignore[arg-type]
        SimpleNamespace(query="考题风格帮我分析一下", contextQuery=context_query, filters={}),
        current_user_id=7,
    )
    body = json.loads(str(response["output"]).removeprefix("<json>").removesuffix("</json>"))
    prompt = captured["user_prompt"]

    assert "ESD-电子系统设计-2021年真题及答案" in captured["rank_query"]
    assert "用户：后续讨论" not in captured["rank_query"]
    assert "助手：后续讨论" not in captured["rank_query"]
    assert prompt["query_plan"]["intent"] == "exam_trend_analysis"
    assert prompt["query_plan"]["course_terms"] == ["电子系统设计"]
    assert "最近上下文关键词" not in prompt["query_plan"]["search_terms"]
    assert "用户：后续讨论" not in prompt["conversation_focus"]
    assert "助手：后续讨论" not in prompt["conversation_focus"]
    assert body["recommendations"][0]["material_id"] == 501
    metrics.clear()


def test_agent_exam_trend_closed_loop_prompt_and_response_contract(monkeypatch) -> None:
    captured: dict[str, Any] = {}
    metrics = get_runtime_metrics()
    metrics.clear()
    materials = [
        _material(
            101,
            title="通信原理四年真题解析",
            description="2021-2024 通信原理期末真题和答案解析",
            downloads=90,
        ),
        _material(
            202,
            title="通信原理期末速成讲义",
            description="通信原理高频考点、速成提纲和例题解析",
            downloads=40,
        ),
    ]
    evidence = _evidence()
    settings = Settings(
        ai_agent_provider="openai-compatible",
        ai_agent_base_url="https://example.test/v1",
        ai_agent_api_key="test-key",
        ai_agent_model="demo-model",
        ai_agent_max_context_materials=3,
    )
    monkeypatch.setattr("app.services.ai_service.get_settings", lambda: settings)

    class FakePdfEvidenceService:
        def collect_for_materials(
            self,
            received_materials: list[MaterialRecord],
            query: str,
            *,
            current_user_id: int | None,
        ) -> list[MaterialPageEvidence]:
            captured["pdf_material_ids"] = [int(item.id) for item in received_materials]
            captured["pdf_query"] = query
            captured["pdf_user_id"] = current_user_id
            return [evidence]

    class FakeMemoryService:
        def collect(
            self,
            session: object,
            *,
            query: str,
            materials: list[MaterialRecord],
            current_user_id: int | None,
            pdf_evidence: list[MaterialPageEvidence],
        ) -> AgentMemoryContext:
            del session
            captured["memory_query"] = query
            captured["memory_material_ids"] = [int(item.id) for item in materials]
            captured["memory_user_id"] = current_user_id
            captured["memory_evidence_pages"] = [item.page for item in pdf_evidence]
            return AgentMemoryContext(
                platform={
                    "pdf_year_signals": [{"value": "2024", "count": 1}],
                    "pdf_question_type_signals": [{"value": "计算题", "count": 1}],
                    "high_signal_materials": [{"material_id": 101, "title": "通信原理四年真题解析"}],
                },
                user={"profile": {"school": "电子科技大学", "major": "通信工程"}},
            )

    service = AiService(
        read_repo=None,
        material_repo=None,
        pdf_evidence_service=FakePdfEvidenceService(),
        memory_service=FakeMemoryService(),
        query_planner_service=AgentQueryPlannerService(),
        course_memory_service=AgentCourseMemoryService(),
    )  # type: ignore[arg-type]
    monkeypatch.setattr(service, "_rank_materials", lambda session, query, filters: materials)

    def fake_call_agent_model(settings: Settings, system_prompt: str, user_prompt: dict[str, Any]) -> str:
        captured["system_prompt"] = system_prompt
        captured["user_prompt"] = user_prompt
        return json.dumps(
            {
                "answer": "我看了《通信原理四年真题解析》第 3 页，通信原理近年常考计算题，重点是调制、解调和误码率。",
                "recommendations": [
                    {"material_id": 101, "reason": "含 2024 年第3题页级证据"},
                    {"material_id": 999, "reason": "模型编造的资料"},
                ],
                "evidence_sources": [
                    {"material_id": 101, "page": 3, "title": "通信原理四年真题解析"},
                    {"material_id": 101, "page": 99, "title": "未读取页"},
                ],
                "followup_questions": ["要不要按年份整理题型？", "是否需要两周复习顺序？"],
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
    prompt = captured["user_prompt"]

    assert captured["pdf_material_ids"] == [101, 202]
    assert captured["pdf_query"] == "通信原理往年题常考什么"
    assert captured["pdf_user_id"] == 7
    assert captured["memory_material_ids"] == [101, 202]
    assert captured["memory_evidence_pages"] == [3]

    assert prompt["query_plan"]["intent"] == "exam_trend_analysis"
    assert "read_relevant_pdf_pages" in prompt["query_plan"]["evidence_tasks"]
    assert "aggregate_question_type_signals" in prompt["query_plan"]["evidence_tasks"]
    assert prompt["pdf_evidence"][0]["page"] == 3
    assert prompt["pdf_evidence"][0]["question_numbers"] == ["第3题"]
    assert prompt["pdf_evidence"][0]["chapter_signals"] == ["第2章 调制解调"]
    assert prompt["pdf_evidence"][0]["solution_signals"] == ["参考答案", "解题步骤"]
    assert prompt["pdf_evidence"][0]["source_type"] == "past_exam"
    assert prompt["pdf_evidence"][0]["score_points"] == [10]
    assert prompt["pdf_evidence"][0]["difficulty_signals"] == ["综合", "偏难"]
    assert prompt["pdf_evidence"][0]["visual_signals"] == ["公式", "图示"]
    assert prompt["pdf_evidence"][0]["anchor_terms"] == ["第3题", "计算题"]
    assert prompt["pdf_evidence"][0]["anchor_text"] == "2024 通信原理第3题计算题考调制、解调和误码率。"
    assert "aggregate_score_point_signals" in prompt["query_plan"]["evidence_tasks"]
    assert "aggregate_difficulty_signals" in prompt["query_plan"]["evidence_tasks"]
    assert "preserve_formula_or_visual_page_refs" in prompt["query_plan"]["evidence_tasks"]
    assert "cite_anchor_snippets" in prompt["query_plan"]["evidence_tasks"]
    assert prompt["candidate_materials"][0]["quality_score"] > 0
    assert "quality_signals" in prompt["candidate_materials"][0]
    assert "risk_signals" in prompt["candidate_materials"][0]
    assert "已读取 PDF 第 3 页证据" in prompt["candidate_materials"][0]["reason"]
    assert "题型信号：计算题" in prompt["candidate_materials"][0]["reason"]
    assert "章节/模块信号：第2章 调制解调" in prompt["candidate_materials"][0]["reason"]
    assert "答案/解析信号：参考答案、解题步骤" in prompt["candidate_materials"][0]["reason"]
    assert "题号信号：第3题" in prompt["candidate_materials"][0]["reason"]
    assert "分值信号：10分" in prompt["candidate_materials"][0]["reason"]
    assert "难度信号：综合、偏难" in prompt["candidate_materials"][0]["reason"]
    assert "公式/图表信号：公式、图示" in prompt["candidate_materials"][0]["reason"]
    assert "quality_signals" in captured["system_prompt"]
    assert "anchor_text" in captured["system_prompt"]
    assert prompt["memory_context"]["platform_collective_memory"]["pdf_question_type_signals"][0]["value"] == "计算题"
    assert prompt["memory_context"]["user_personal_memory"]["profile"]["major"] == "通信工程"
    assert prompt["course_memory_card"]["course"] == "通信原理"
    assert prompt["course_memory_card"]["evidence_coverage"]["pdf_evidence_page_count"] == 1
    assert prompt["course_memory_card"]["confidence_assessment"]["level"] == "medium"
    assert prompt["course_memory_card"]["page_references"][0]["question_numbers"] == ["第3题"]
    assert prompt["course_memory_card"]["page_references"][0]["chapter_signals"] == ["第2章 调制解调"]
    assert prompt["course_memory_card"]["page_references"][0]["solution_signals"] == ["参考答案", "解题步骤"]
    assert prompt["course_memory_card"]["page_references"][0]["anchor_terms"] == ["第3题", "计算题"]
    assert prompt["course_memory_card"]["page_references"][0]["anchor_text"] == "2024 通信原理第3题计算题考调制、解调和误码率。"
    assert prompt["course_memory_card"]["score_point_distribution"] == [{"value": "10", "count": 1}]
    assert prompt["course_memory_card"]["chapter_distribution"] == [{"value": "第2章 调制解调", "count": 1}]
    assert prompt["course_memory_card"]["solution_signal_distribution"] == [{"value": "参考答案", "count": 1}, {"value": "解题步骤", "count": 1}]
    assert prompt["course_memory_card"]["difficulty_distribution"] == [{"value": "综合", "count": 1}, {"value": "偏难", "count": 1}]
    assert prompt["course_memory_card"]["visual_signal_distribution"] == [{"value": "公式", "count": 1}, {"value": "图示", "count": 1}]

    assert body["answer"].startswith("我看了《通信原理四年真题解析》第 3 页")
    assert {item["material_id"] for item in body["recommendations"]} == {101, 202}
    assert body["recommendations"][0]["reason"] == "含 2024 年第3题页级证据"
    assert body["evidence_sources"] == [
        {
            "material_id": 101,
            "title": "通信原理四年真题解析",
            "page": 3,
            "excerpt": "2024 通信原理第3题计算题考调制、解调和误码率。",
            "years": ["2024"],
            "question_types": ["计算题"],
            "question_numbers": ["第3题"],
            "source_type": "past_exam",
        }
    ]
    assert "score_points" not in body["evidence_sources"][0]
    assert "difficulty_signals" not in body["evidence_sources"][0]
    assert "visual_signals" not in body["evidence_sources"][0]
    assert "anchor_terms" not in body["evidence_sources"][0]
    assert "anchor_text" not in body["evidence_sources"][0]
    assert body["followup_questions"] == ["要不要按年份整理题型？", "是否需要两周复习顺序？"]
    assert "memory_context" not in json.dumps(body, ensure_ascii=False)
    assert "query_plan" not in json.dumps(body, ensure_ascii=False)

    metrics_text = metrics.render_prometheus(settings)
    assert (
        'studyhub_ai_agent_runs_total{provider="openai-compatible",status="model_success",'
        'pdf_evidence="yes",memory_context="yes",course_memory_card="yes"} 1'
    ) in metrics_text
    assert (
        'studyhub_ai_agent_run_duration_seconds_count{provider="openai-compatible",status="model_success",'
        'pdf_evidence="yes",memory_context="yes",course_memory_card="yes"} 1'
    ) in metrics_text
    metrics.clear()


def test_agent_local_study_plan_uses_structured_query_constraints(monkeypatch) -> None:
    metrics = get_runtime_metrics()
    metrics.clear()
    settings = Settings(ai_agent_provider="local")
    monkeypatch.setattr("app.services.ai_service.get_settings", lambda: settings)

    service = AiService(
        read_repo=None,
        material_repo=None,
        query_planner_service=AgentQueryPlannerService(),
    )  # type: ignore[arg-type]
    monkeypatch.setattr(
        service,
        "_rank_materials",
        lambda session, query, filters: [
            _material(
                101,
                title="通信原理期末速成讲义",
                description="通信原理高频考点、速成提纲和例题解析",
                downloads=90,
            )
        ],
    )

    response = service.recommend(
        object(),  # type: ignore[arg-type]
        SimpleNamespace(query="我两周后考试，目标85分，每天2小时，调制和误码率很薄弱，应该怎么复习通信原理？", filters={}),
        current_user_id=7,
    )
    body = json.loads(str(response["output"]).removeprefix("<json>").removesuffix("</json>"))

    assert "距离考试约 14 天" in body["answer"]
    assert "目标约 85 分" in body["answer"]
    assert "每天可用约 2 小时" in body["answer"]
    assert "薄弱点先放在 调制、误码率" in body["answer"]
    assert body["followup_questions"][0] == "要不要我按 14 天拆成每日复习安排？"
    assert "query_plan" not in json.dumps(body, ensure_ascii=False)
    metrics.clear()


def test_agent_local_study_plan_uses_query_learning_preferences(monkeypatch) -> None:
    metrics = get_runtime_metrics()
    metrics.clear()
    settings = Settings(ai_agent_provider="local")
    monkeypatch.setattr("app.services.ai_service.get_settings", lambda: settings)

    service = AiService(
        read_repo=None,
        material_repo=None,
        query_planner_service=AgentQueryPlannerService(),
    )  # type: ignore[arg-type]
    monkeypatch.setattr(
        service,
        "_rank_materials",
        lambda session, query, filters: [
            _material(
                101,
                title="通信原理期末速成讲义",
                description="通信原理高频考点、速成提纲和例题解析",
                downloads=90,
            )
        ],
    )

    response = service.recommend(
        object(),  # type: ignore[arg-type]
        SimpleNamespace(query="我基础差，想考前速成，多刷真题，但要一步步讲清楚，通信原理怎么复习？", filters={}),
        current_user_id=7,
    )
    body = json.loads(str(response["output"]).removeprefix("<json>").removesuffix("</json>"))

    assert "结合你的学习偏好" in body["answer"]
    assert "基础偏弱" in body["answer"]
    assert "短期冲刺" in body["answer"]
    assert "刷题训练" in body["answer"]
    assert "learning_preferences" not in json.dumps(body, ensure_ascii=False)
    metrics.clear()


def test_agent_local_pdf_summary_uses_intent_specific_evidence(monkeypatch) -> None:
    metrics = get_runtime_metrics()
    metrics.clear()
    settings = Settings(ai_agent_provider="local")
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
    monkeypatch.setattr(
        service,
        "_rank_materials",
        lambda session, query, filters: [
            _material(
                101,
                title="通信原理四年真题解析",
                description="2021-2024 通信原理期末真题和答案解析",
                downloads=90,
            )
        ],
    )

    response = service.recommend(
        object(),  # type: ignore[arg-type]
        SimpleNamespace(query="这份通信原理资料讲什么", filters={}),
        current_user_id=7,
    )
    body = json.loads(str(response["output"]).removeprefix("<json>").removesuffix("</json>"))

    assert "资料内容结构" in body["answer"]
    assert "资料类型偏向 往年真题" in body["answer"]
    assert "章节/模块信号 第2章 调制解调" in body["answer"]
    assert "答案/解析信号 参考答案、解题步骤" in body["answer"]
    assert "涉及知识点 调制、解调、误码率" in body["answer"]
    assert "出现分值 10分" in body["answer"]
    assert "难度信号 综合、偏难" in body["answer"]
    assert "公式/图表页信号 公式、图示" in body["answer"]
    assert "建议先读《通信原理四年真题解析》第 3 页建立概览" in body["answer"]
    assert body["followup_questions"] == [
        "要不要我继续按章节或页码拆解这份资料？",
        "是否需要标出最适合先看的重点页面？",
    ]
    metrics.clear()


def test_agent_local_material_fit_assessment_uses_evidence_and_profile(monkeypatch) -> None:
    metrics = get_runtime_metrics()
    metrics.clear()
    settings = Settings(ai_agent_provider="local")
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

    class FakeMemoryService:
        def collect(
            self,
            session: object,
            *,
            query: str,
            materials: list[MaterialRecord],
            current_user_id: int | None,
            pdf_evidence: list[MaterialPageEvidence],
        ) -> AgentMemoryContext:
            del session, query, materials, current_user_id, pdf_evidence
            return AgentMemoryContext(
                platform={},
                user={"profile": {"school": "电子科技大学", "college": "信通", "major": "通信工程"}},
            )

    service = AiService(
        read_repo=None,
        material_repo=None,
        pdf_evidence_service=FakePdfEvidenceService(),
        memory_service=FakeMemoryService(),
        query_planner_service=AgentQueryPlannerService(),
        course_memory_service=AgentCourseMemoryService(),
    )  # type: ignore[arg-type]
    monkeypatch.setattr(
        service,
        "_rank_materials",
        lambda session, query, filters: [
            _material(
                101,
                title="通信原理四年真题解析",
                description="2021-2024 通信原理期末真题和答案解析",
                downloads=90,
            )
        ],
    )

    response = service.recommend(
        object(),  # type: ignore[arg-type]
        SimpleNamespace(query="这份通信原理真题适合我现在看吗", filters={}),
        current_user_id=7,
    )
    body = json.loads(str(response["output"]).removeprefix("<json>").removesuffix("</json>"))

    assert "适合度判断" in body["answer"]
    assert "用途偏向 往年真题" in body["answer"]
    assert "章节/模块覆盖 第2章 调制解调" in body["answer"]
    assert "答案/解析覆盖 参考答案、解题步骤" in body["answer"]
    assert "它更适合考前刷题和题型复盘" in body["answer"]
    assert "如果基础还不稳，建议先读引用页确认难度" in body["answer"]
    assert "可先从《通信原理四年真题解析》第 3 页开始" in body["answer"]
    assert "我会优先按你的电子科技大学/信通/通信工程背景来判断匹配度" in body["answer"]
    assert body["followup_questions"] == [
        "你现在是补基础、刷题冲刺还是查漏补缺？",
        "要不要我把这份资料拆成先看页和后看页？",
        "是否需要结合你的专业和年级调整推荐顺序？",
    ]
    assert "query_plan" not in json.dumps(body, ensure_ascii=False)
    metrics.clear()


def test_agent_local_exam_trend_uses_collective_strategy_sequence(monkeypatch) -> None:
    metrics = get_runtime_metrics()
    metrics.clear()
    settings = Settings(ai_agent_provider="local")
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

    class FakeMemoryService:
        def collect(
            self,
            session: object,
            *,
            query: str,
            materials: list[MaterialRecord],
            current_user_id: int | None,
            pdf_evidence: list[MaterialPageEvidence],
        ) -> AgentMemoryContext:
            del session, query, materials, current_user_id, pdf_evidence
            return AgentMemoryContext(
                platform={
                    "study_strategy_signals": [
                        {"value": "先建立知识框架", "count": 2},
                        {"value": "刷真题", "count": 2},
                    ],
                    "experience_materials": [
                        {
                            "material_id": 202,
                            "title": "通信原理考前复习经验分享",
                            "study_strategy_signals": ["先建立知识框架", "刷真题"],
                        }
                    ],
                },
                user=None,
            )

    service = AiService(
        read_repo=None,
        material_repo=None,
        pdf_evidence_service=FakePdfEvidenceService(),
        memory_service=FakeMemoryService(),
        query_planner_service=AgentQueryPlannerService(),
        course_memory_service=AgentCourseMemoryService(),
    )  # type: ignore[arg-type]
    monkeypatch.setattr(
        service,
        "_rank_materials",
        lambda session, query, filters: [
            _material(
                101,
                title="通信原理四年真题解析",
                description="2021-2024 通信原理期末真题和答案解析",
                downloads=90,
            ),
            _material(
                202,
                title="通信原理考前复习经验分享",
                description="先建立知识框架，再刷真题。",
                downloads=30,
            ),
        ],
    )

    response = service.recommend(
        object(),  # type: ignore[arg-type]
        SimpleNamespace(query="通信原理往年题常考什么", filters={}),
        current_user_id=7,
    )
    body = json.loads(str(response["output"]).removeprefix("<json>").removesuffix("</json>"))

    assert "建议按这个顺序处理：先看高频题型、再核对年份趋势、最后按页码打开真题资料查漏补缺、先建立知识框架、刷真题" in body["answer"]
    assert "study_strategy_distribution" not in json.dumps(body, ensure_ascii=False)
    assert "experience_materials" not in json.dumps(body, ensure_ascii=False)
    metrics.clear()


def test_agent_local_fallback_uses_collective_memory_without_pdf_evidence(monkeypatch) -> None:
    metrics = get_runtime_metrics()
    metrics.clear()
    settings = Settings(ai_agent_provider="local")
    monkeypatch.setattr("app.services.ai_service.get_settings", lambda: settings)

    class FakeMemoryService:
        def collect(
            self,
            session: object,
            *,
            query: str,
            materials: list[MaterialRecord],
            current_user_id: int | None,
            pdf_evidence: list[MaterialPageEvidence],
        ) -> AgentMemoryContext:
            del session, query, materials, current_user_id, pdf_evidence
            return AgentMemoryContext(
                platform={
                    "pdf_year_signals": [{"value": "2021", "count": 1}],
                    "pdf_question_type_signals": [
                        {"value": "计算题", "count": 3},
                        {"value": "简答题", "count": 2},
                    ],
                    "pdf_source_type_signals": [{"value": "past_exam", "count": 2}],
                    "study_strategy_signals": [
                        {"value": "先刷真题", "count": 2},
                        {"value": "再复盘错题", "count": 1},
                    ],
                },
                user=None,
            )

    service = AiService(
        read_repo=None,
        material_repo=None,
        memory_service=FakeMemoryService(),
        query_planner_service=AgentQueryPlannerService(),
        course_memory_service=AgentCourseMemoryService(),
    )  # type: ignore[arg-type]
    monkeypatch.setattr(
        service,
        "_rank_materials",
        lambda session, query, filters: [
            _material(
                101,
                title="通信原理四年真题解析",
                description="2021 通信原理期末真题和答案解析",
                downloads=90,
            )
        ],
    )

    response = service.recommend(
        object(),  # type: ignore[arg-type]
        SimpleNamespace(query="通信原理往年题常考什么", filters={}),
        current_user_id=7,
    )
    body = json.loads(str(response["output"]).removeprefix("<json>").removesuffix("</json>"))

    assert "当前暂缺可引用的 PDF 页级证据" in body["answer"]
    assert "年份信号包括 2021" in body["answer"]
    assert "资料类型偏向 往年真题" in body["answer"]
    assert "题型信号集中在 计算题、简答题" in body["answer"]
    assert "经验策略偏向 先刷真题、再复盘错题" in body["answer"]
    assert "这些结论需要保持保守" in body["answer"]
    assert "query_plan" not in json.dumps(body, ensure_ascii=False)
    assert "memory_context" not in json.dumps(body, ensure_ascii=False)
    assert "course_memory_card" not in json.dumps(body, ensure_ascii=False)
    assert "study_strategy_distribution" not in json.dumps(body, ensure_ascii=False)
    metrics.clear()


def test_agent_local_exam_trend_handles_multi_material_scope(monkeypatch) -> None:
    metrics = get_runtime_metrics()
    metrics.clear()
    settings = Settings(ai_agent_provider="local")
    monkeypatch.setattr("app.services.ai_service.get_settings", lambda: settings)
    second_evidence = MaterialPageEvidence(
        material_id=202,
        title="通信原理六年期末题",
        page=5,
        text="2023 通信原理第5题简答题考系统框图和判决。",
        score=45,
        years=("2023",),
        question_types=("简答题",),
        knowledge_signals=("判决",),
        question_numbers=("第5题",),
        source_type="past_exam",
        score_points=(8,),
        difficulty_signals=("中等",),
        visual_signals=("图示",),
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
            return [_evidence(), second_evidence]

    service = AiService(
        read_repo=None,
        material_repo=None,
        pdf_evidence_service=FakePdfEvidenceService(),
        query_planner_service=AgentQueryPlannerService(),
        course_memory_service=AgentCourseMemoryService(),
    )  # type: ignore[arg-type]
    monkeypatch.setattr(
        service,
        "_rank_materials",
        lambda session, query, filters: [
            _material(
                101,
                title="通信原理四年真题解析",
                description="2021-2024 通信原理期末真题和答案解析",
                downloads=90,
            ),
            _material(
                202,
                title="通信原理六年期末题",
                description="2018-2023 通信原理期末题型整理",
                downloads=70,
            ),
        ],
    )

    response = service.recommend(
        object(),  # type: ignore[arg-type]
        SimpleNamespace(query="帮我分析这几份通信原理真题的关键题型", filters={}),
        current_user_id=7,
    )
    body = json.loads(str(response["output"]).removeprefix("<json>").removesuffix("</json>"))

    assert "我会按多份资料对比处理，当前已读证据覆盖 2 份资料" in body["answer"]
    assert "跨资料共同题型暂未在已读页中重合" in body["answer"]
    assert "资料差异包括 《通信原理四年真题解析》第 3 页偏向题型 计算题、知识点 调制、解调、误码率、年份 2024" in body["answer"]
    assert "《通信原理六年期末题》第 5 页偏向题型 简答题、知识点 判决、年份 2023" in body["answer"]
    assert "年份题型对应 2024: 计算题、2023: 简答题" in body["answer"]
    assert "题型集中在 计算题、简答题" in body["answer"]
    assert "《通信原理六年期末题》第 5 页" in body["answer"]
    assert "material_scope" not in json.dumps(body, ensure_ascii=False)
    assert body["evidence_sources"][1]["material_id"] == 202
    metrics.clear()


def test_agent_local_problem_tutoring_uses_intent_specific_evidence(monkeypatch) -> None:
    metrics = get_runtime_metrics()
    metrics.clear()
    settings = Settings(ai_agent_provider="local")
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
    monkeypatch.setattr(
        service,
        "_rank_materials",
        lambda session, query, filters: [
            _material(
                101,
                title="通信原理四年真题解析",
                description="2021-2024 通信原理期末真题和答案解析",
                downloads=90,
            )
        ],
    )

    response = service.recommend(
        object(),  # type: ignore[arg-type]
        SimpleNamespace(query="这道通信原理第3题不会怎么做", filters={}),
        current_user_id=7,
    )
    body = json.loads(str(response["output"]).removeprefix("<json>").removesuffix("</json>"))

    assert "这类问题可以先定位到 《通信原理四年真题解析》第 3 页（第3题）" in body["answer"]
    assert "先按你提到的卡点处理：计算步骤" in body["answer"]
    assert "题号边界：第3题" in body["answer"]
    assert "先判断题型：计算题" in body["answer"]
    assert "先定位章节/模块：第2章 调制解调" in body["answer"]
    assert "再对照答案/解析：参考答案、解题步骤" in body["answer"]
    assert "再抓核心知识点：调制、解调、误码率" in body["answer"]
    assert "按分值投入时间：10分" in body["answer"]
    assert "预估难度：综合、偏难" in body["answer"]
    assert "注意公式/图表信息：公式、图示" in body["answer"]
    assert body["followup_questions"] == [
        "你卡住的是概念理解、公式推导还是计算步骤？",
        "要不要我按同类题型再找几页练习？",
    ]
    metrics.clear()


def test_agent_model_failure_uses_structured_local_exam_trend_fallback(monkeypatch) -> None:
    metrics = get_runtime_metrics()
    metrics.clear()
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
    monkeypatch.setattr(
        service,
        "_rank_materials",
        lambda session, query, filters: [
            _material(
                101,
                title="通信原理四年真题解析",
                description="2021-2024 通信原理期末真题和答案解析",
                downloads=90,
            )
        ],
    )

    def raise_model_error(settings: Settings, system_prompt: str, user_prompt: dict[str, Any]) -> str:
        del settings, system_prompt, user_prompt
        raise RuntimeError("model down")

    monkeypatch.setattr(service, "_call_agent_model", raise_model_error)

    response = service.recommend(
        object(),  # type: ignore[arg-type]
        SimpleNamespace(query="通信原理往年题常考什么", filters={}),
        current_user_id=7,
    )
    body = json.loads(str(response["output"]).removeprefix("<json>").removesuffix("</json>"))

    assert "年份信号包括 2024" in body["answer"]
    assert "章节/模块信号包括 第2章 调制解调" in body["answer"]
    assert "答案/解析信号包括 参考答案、解题步骤" in body["answer"]
    assert "题型集中在 计算题" in body["answer"]
    assert "高频知识点包括 调制、解调、误码率" in body["answer"]
    assert "分值信号包括 10分" in body["answer"]
    assert "难度信号包括 综合、偏难" in body["answer"]
    assert "需关注的公式/图表信号包括 公式、图示" in body["answer"]
    assert "《通信原理四年真题解析》第 3 页" in body["answer"]
    assert "已读取 PDF 第 3 页证据" in body["recommendations"][0]["reason"]
    assert "年份信号：2024" in body["recommendations"][0]["reason"]
    assert "题号信号：第3题" in body["recommendations"][0]["reason"]
    assert "分值信号：10分" in body["recommendations"][0]["reason"]
    assert "难度信号：综合、偏难" in body["recommendations"][0]["reason"]
    assert "公式/图表信号：公式、图示" in body["recommendations"][0]["reason"]
    assert "质量信号：" in body["recommendations"][0]["reason"]
    assert "需留意：" in body["recommendations"][0]["reason"]
    assert body["evidence_sources"][0]["question_numbers"] == ["第3题"]
    assert body["followup_questions"] == [
        "要不要我按年份整理常考题型？",
        "是否需要把这些资料整理成两周复习顺序？",
        "要不要我按题号列出优先复盘清单？",
    ]
    metrics_text = metrics.render_prometheus(settings)
    assert (
        'studyhub_ai_agent_runs_total{provider="openai-compatible",status="model_fallback",'
        'pdf_evidence="yes",memory_context="no",course_memory_card="yes"} 1'
    ) in metrics_text
    metrics.clear()


def test_agent_local_exam_trend_prioritizes_requested_focus_dimensions(monkeypatch) -> None:
    metrics = get_runtime_metrics()
    metrics.clear()
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
    monkeypatch.setattr(
        service,
        "_rank_materials",
        lambda session, query, filters: [
            _material(
                101,
                title="通信原理四年真题解析",
                description="2021-2024 通信原理期末真题和答案解析",
                downloads=90,
            )
        ],
    )

    def raise_model_error(settings: Settings, system_prompt: str, user_prompt: dict[str, Any]) -> str:
        del settings, system_prompt, user_prompt
        raise RuntimeError("model down")

    monkeypatch.setattr(service, "_call_agent_model", raise_model_error)

    response = service.recommend(
        object(),  # type: ignore[arg-type]
        SimpleNamespace(query="通信原理近几年分值结构、难度变化和公式图表页怎么分布？", filters={}),
        current_user_id=7,
    )
    body = json.loads(str(response["output"]).removeprefix("<json>").removesuffix("</json>"))
    answer = body["answer"]

    assert "年份信号包括 2024" in answer
    assert "分值信号包括 10分" in answer
    assert "难度信号包括 综合、偏难" in answer
    assert "需关注的公式/图表信号包括 公式、图示" in answer
    assert answer.index("分值信号包括 10分") < answer.index("章节/模块信号包括 第2章 调制解调")
    assert answer.index("难度信号包括 综合、偏难") < answer.index("章节/模块信号包括 第2章 调制解调")
    assert answer.index("需关注的公式/图表信号包括 公式、图示") < answer.index("章节/模块信号包括 第2章 调制解调")
    assert "exam_analysis_focus" not in json.dumps(body, ensure_ascii=False)
    metrics.clear()


def test_agent_replaces_model_no_candidate_answer_when_local_materials_exist(monkeypatch) -> None:
    metrics = get_runtime_metrics()
    metrics.clear()
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
        course_memory_service=AgentCourseMemoryService(),
    )  # type: ignore[arg-type]
    monkeypatch.setattr(
        service,
        "_rank_materials",
        lambda session, query, filters: [
            MaterialRecord(
                id=501,
                title="ESD-电子系统设计-2021年真题及答案",
                description="电子系统设计 2021 年真题、样卷答案和期末考题整理",
                tags_json=json.dumps(["电子系统设计", "真题", "答案"], ensure_ascii=False),
                school="电子科技大学",
                college="自动化",
                major="电子系统设计",
                file_type="pdf",
                is_free=True,
                download_count=30,
                rating_avg=4.6,
                rating_count=4,
            )
        ],
    )

    def fake_no_candidate_answer(settings: Settings, system_prompt: str, user_prompt: dict[str, Any]) -> str:
        del settings, system_prompt, user_prompt
        return json.dumps(
            {
                "answer": "目前我这边没有收到任何 ESD 的候选资料，所以不能基于指定资料直接分析考题风格。",
                "followup_questions": ["你可以把真题发给我吗？"],
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(service, "_call_agent_model", fake_no_candidate_answer)

    response = service.recommend(
        object(),  # type: ignore[arg-type]
        SimpleNamespace(query="esd考题风格帮我分析一下", filters={}),
        current_user_id=7,
    )
    body = json.loads(str(response["output"]).removeprefix("<json>").removesuffix("</json>"))

    assert "没有收到任何" not in body["answer"]
    assert "StudyHub 资料库找到" in body["answer"]
    assert "ESD-电子系统设计-2021年真题及答案" in body["answer"]
    assert body["recommendations"][0]["material_id"] == 501
    assert "电子系统设计" in body["recommendations"][0]["title"]
    metrics.clear()


def test_agent_blocks_non_learning_query_before_retrieval(monkeypatch) -> None:
    settings = Settings(ai_agent_provider="local")
    monkeypatch.setattr("app.services.ai_service.get_settings", lambda: settings)
    service = AiService(read_repo=None, material_repo=None)  # type: ignore[arg-type]

    def fail_rank_materials(session: object, query: str, filters: dict[str, Any]) -> list[MaterialRecord]:
        del session, query, filters
        raise AssertionError("non-learning query should not trigger retrieval")

    monkeypatch.setattr(service, "_rank_materials", fail_rank_materials)

    response = service.recommend(
        object(),  # type: ignore[arg-type]
        SimpleNamespace(query="明天天气怎么样", filters={}, imageAttachments=[]),
        current_user_id=7,
    )
    body = json.loads(str(response["output"]).removeprefix("<json>").removesuffix("</json>"))

    assert "只处理课程学习" in body["answer"]
    assert "明天天气" not in body["answer"]
    assert "recommendations" not in body


def test_agent_blocks_non_learning_query_even_with_learning_context(monkeypatch) -> None:
    settings = Settings(ai_agent_provider="local")
    monkeypatch.setattr("app.services.ai_service.get_settings", lambda: settings)
    service = AiService(read_repo=None, material_repo=None)  # type: ignore[arg-type]

    def fail_rank_materials(session: object, query: str, filters: dict[str, Any]) -> list[MaterialRecord]:
        del session, query, filters
        raise AssertionError("non-learning query should not inherit learning context")

    monkeypatch.setattr(service, "_rank_materials", fail_rank_materials)

    response = service.recommend(
        object(),  # type: ignore[arg-type]
        SimpleNamespace(
            query="明天天气怎么样",
            contextQuery="用户：通信原理往年题常考什么 助手：推荐资料：《通信原理四年真题解析》",
            filters={},
            imageAttachments=[],
        ),
        current_user_id=7,
    )
    body = json.loads(str(response["output"]).removeprefix("<json>").removesuffix("</json>"))

    assert "只处理课程学习" in body["answer"]
    assert "recommendations" not in body


def test_agent_allows_context_dependent_learning_followup(monkeypatch) -> None:
    settings = Settings(ai_agent_provider="local")
    monkeypatch.setattr("app.services.ai_service.get_settings", lambda: settings)
    service = AiService(read_repo=None, material_repo=None)  # type: ignore[arg-type]
    captured: dict[str, Any] = {}

    def fake_rank_materials(session: object, query: str, filters: dict[str, Any]) -> list[MaterialRecord]:
        del session, filters
        captured["rank_query"] = query
        return [
            _material(
                702,
                title="通信原理四年真题解析",
                description="通信原理期末真题、答案和解析",
                downloads=20,
            )
        ]

    monkeypatch.setattr(service, "_rank_materials", fake_rank_materials)

    response = service.recommend(
        object(),  # type: ignore[arg-type]
        SimpleNamespace(
            query="继续分析一下",
            contextQuery="用户：通信原理往年题常考什么 助手：推荐资料：《通信原理四年真题解析》",
            filters={},
            imageAttachments=[],
        ),
        current_user_id=7,
    )
    body = json.loads(str(response["output"]).removeprefix("<json>").removesuffix("</json>"))

    assert "最近上下文关键词" in captured["rank_query"]
    assert "通信原理" in captured["rank_query"]
    assert body["recommendations"][0]["material_id"] == 702


def test_agent_image_attachment_local_fallback_keeps_learning_boundary(monkeypatch) -> None:
    settings = Settings(ai_agent_provider="local")
    monkeypatch.setattr("app.services.ai_service.get_settings", lambda: settings)
    service = AiService(read_repo=None, material_repo=None)  # type: ignore[arg-type]
    monkeypatch.setattr(
        service,
        "_rank_materials",
        lambda session, query, filters: [
            _material(
                701,
                title="通信原理题型解析",
                description="通信原理期末题型、答案和解析",
                downloads=20,
            )
        ],
    )

    response = service.recommend(
        object(),  # type: ignore[arg-type]
        SimpleNamespace(
            query="帮我分析这张题目截图",
            filters={},
            imageAttachments=[
                {
                    "name": "question.png",
                    "mimeType": "image/png",
                    "dataUrl": "data:image/png;base64,aW1hZ2U=",
                    "sizeBytes": 128,
                }
            ],
        ),
        current_user_id=7,
    )
    body = json.loads(str(response["output"]).removeprefix("<json>").removesuffix("</json>"))

    assert body["answer"].startswith("我已收到你发的图片")
    assert body["recommendations"][0]["material_id"] == 701
