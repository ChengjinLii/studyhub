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
        question_numbers=("第3题",),
        source_type="past_exam",
        score_points=(10,),
        difficulty_signals=("综合", "偏难"),
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
    assert prompt["pdf_evidence"][0]["source_type"] == "past_exam"
    assert prompt["pdf_evidence"][0]["score_points"] == [10]
    assert prompt["pdf_evidence"][0]["difficulty_signals"] == ["综合", "偏难"]
    assert "aggregate_score_point_signals" in prompt["query_plan"]["evidence_tasks"]
    assert "aggregate_difficulty_signals" in prompt["query_plan"]["evidence_tasks"]
    assert prompt["candidate_materials"][0]["quality_score"] > 0
    assert "quality_signals" in prompt["candidate_materials"][0]
    assert "risk_signals" in prompt["candidate_materials"][0]
    assert "已读取 PDF 第 3 页证据" in prompt["candidate_materials"][0]["reason"]
    assert "题型信号：计算题" in prompt["candidate_materials"][0]["reason"]
    assert "题号信号：第3题" in prompt["candidate_materials"][0]["reason"]
    assert "分值信号：10分" in prompt["candidate_materials"][0]["reason"]
    assert "难度信号：综合、偏难" in prompt["candidate_materials"][0]["reason"]
    assert "quality_signals" in captured["system_prompt"]
    assert prompt["memory_context"]["platform_collective_memory"]["pdf_question_type_signals"][0]["value"] == "计算题"
    assert prompt["memory_context"]["user_personal_memory"]["profile"]["major"] == "通信工程"
    assert prompt["course_memory_card"]["course"] == "通信原理"
    assert prompt["course_memory_card"]["page_references"][0]["question_numbers"] == ["第3题"]
    assert prompt["course_memory_card"]["score_point_distribution"] == [{"value": "10", "count": 1}]
    assert prompt["course_memory_card"]["difficulty_distribution"] == [{"value": "综合", "count": 1}, {"value": "偏难", "count": 1}]

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
    assert "涉及知识点 调制、解调、误码率" in body["answer"]
    assert "出现分值 10分" in body["answer"]
    assert "难度信号 综合、偏难" in body["answer"]
    assert "建议先读《通信原理四年真题解析》第 3 页建立概览" in body["answer"]
    assert body["followup_questions"] == [
        "要不要我继续按章节或页码拆解这份资料？",
        "是否需要标出最适合先看的重点页面？",
    ]
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
    assert "先判断题型：计算题" in body["answer"]
    assert "再抓核心知识点：调制、解调、误码率" in body["answer"]
    assert "按分值投入时间：10分" in body["answer"]
    assert "预估难度：综合、偏难" in body["answer"]
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
    assert "题型集中在 计算题" in body["answer"]
    assert "高频知识点包括 调制、解调、误码率" in body["answer"]
    assert "分值信号包括 10分" in body["answer"]
    assert "难度信号包括 综合、偏难" in body["answer"]
    assert "《通信原理四年真题解析》第 3 页" in body["answer"]
    assert "已读取 PDF 第 3 页证据" in body["recommendations"][0]["reason"]
    assert "年份信号：2024" in body["recommendations"][0]["reason"]
    assert "题号信号：第3题" in body["recommendations"][0]["reason"]
    assert "分值信号：10分" in body["recommendations"][0]["reason"]
    assert "难度信号：综合、偏难" in body["recommendations"][0]["reason"]
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
