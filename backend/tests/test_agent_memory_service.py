from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from app.core.config import Settings
from app.models.materials import MaterialRecord
from app.services.agent_memory_service import AgentMemoryContext, AgentMemoryService
from app.services.ai_service import AiService
from app.services.material_pdf_evidence_service import MaterialPageEvidence


def _material(
    material_id: int,
    *,
    title: str,
    tags: list[str],
    school: str = "电子科技大学",
    college: str = "信通",
    major: str = "通信工程",
    description: str = "通信原理期末真题解析",
    uploader_id: int | None = 2,
    downloads: int = 0,
    rating_avg: float = 0,
    rating_count: int = 0,
    file_storage_key: str | None = "materials/demo.pdf",
) -> MaterialRecord:
    return MaterialRecord(
        id=material_id,
        title=title,
        description=description,
        tags_json=json.dumps(tags, ensure_ascii=False),
        school=school,
        college=college,
        major=major,
        course_category="MAJOR",
        grade_value="大三",
        uploader_id=uploader_id,
        download_count=downloads,
        rating_avg=rating_avg,
        rating_count=rating_count,
        like_count=0,
        is_free=True,
        file_type="pdf",
        file_storage_key=file_storage_key,
    )


def _settings(**overrides: Any) -> Settings:
    values = {
        "ai_agent_memory_context_enabled": True,
        "ai_agent_memory_max_materials": 8,
        "ai_agent_memory_max_interaction_checks": 6,
        "ai_agent_pdf_evidence_max_pages": 6,
    }
    values.update(overrides)
    return Settings(**values)


class _FakeAuthRepo:
    def find_user_by_id(self, session: object, user_id: int) -> SimpleNamespace | None:
        del session
        if user_id != 7:
            return None
        return SimpleNamespace(
            id=7,
            username="private-user",
            email="private@example.com",
            nickname="Private Nick",
            school="电子科技大学",
            college="信通",
            major="通信",
            grade_stages="大三",
        )


class _FakeMaterialRepo:
    def __init__(self) -> None:
        self.checked_downloads: list[int] = []

    def find_favorite(self, session: object, material_id: int, user_id: int) -> object | None:
        del session, user_id
        return object() if material_id == 101 else None

    def has_download(self, session: object, material_id: int, user_id: int) -> bool:
        del session, user_id
        self.checked_downloads.append(material_id)
        return material_id == 102

    def has_purchase(self, session: object, material_id: int, user_id: int) -> bool:
        del session, material_id, user_id
        return False

    def find_rating(self, session: object, material_id: int, user_id: int) -> object | None:
        del session, user_id
        return SimpleNamespace(rating=5) if material_id == 102 else None


def test_agent_memory_context_aggregates_platform_and_current_user_only() -> None:
    material_repo = _FakeMaterialRepo()
    service = AgentMemoryService(_settings(), _FakeAuthRepo(), material_repo)  # type: ignore[arg-type]
    materials = [
        _material(
            101,
            title="通信原理四年真题解析",
            tags=["通信原理", "真题"],
            description="2021-2024 通信原理期末真题、答案解析和常考题型整理",
            downloads=80,
            rating_avg=4.8,
            rating_count=5,
        ),
        _material(102, title="通信原理期末速成笔记", tags=["通信原理", "速成"], downloads=40, rating_avg=4.5),
        _material(
            103,
            title="通信原理考前复习经验分享",
            tags=["经验分享", "通信原理"],
            description="复习攻略：先建立知识框架，再刷真题，最后复盘错题查漏补缺。",
            downloads=30,
            rating_avg=4.9,
            rating_count=3,
        ),
    ]
    evidence = [
        MaterialPageEvidence(
            material_id=101,
            title="通信原理四年真题解析",
            page=3,
            text="第 3 页是通信原理常考题型和解析。",
            score=30,
            years=("2024",),
            question_types=("计算题",),
            knowledge_signals=("调制",),
            chapter_signals=("第2章 调制解调",),
            solution_signals=("参考答案", "解题步骤"),
            question_numbers=("第3题",),
            source_type="past_exam",
            score_points=(10,),
            difficulty_signals=("综合",),
            visual_signals=("公式",),
            anchor_terms=("第3题", "计算题"),
            anchor_text="第 3 页是通信原理常考题型和解析。",
        )
    ]

    context = service.collect(
        object(),  # type: ignore[arg-type]
        query="通信原理往年题常考什么",
        materials=materials,
        current_user_id=7,
        pdf_evidence=evidence,
    )
    prompt = context.to_prompt_payload()

    platform = prompt["platform_collective_memory"]
    assert platform["candidate_count"] == 3
    assert {"value": "通信原理", "count": 3} in platform["top_tags"]
    assert {"value": "经验分享", "count": 1} in platform["top_tags"]
    assert {"value": "先建立知识框架", "count": 1} in platform["study_strategy_signals"]
    assert {"value": "刷真题", "count": 1} in platform["study_strategy_signals"]
    assert {"value": "复盘错题", "count": 1} in platform["study_strategy_signals"]
    assert platform["experience_materials"][0]["material_id"] == 103
    assert platform["experience_materials"][0]["study_strategy_signals"] == ["先建立知识框架", "刷真题", "复盘错题", "冲刺速成"]
    assert {
        "material_id": 101,
        "title": "通信原理四年真题解析",
        "page": 3,
        "question_numbers": ["第3题"],
        "chapter_signals": ["第2章 调制解调"],
        "solution_signals": ["参考答案", "解题步骤"],
        "score_points": [10],
        "difficulty_signals": ["综合"],
        "visual_signals": ["公式"],
        "anchor_terms": ["第3题", "计算题"],
        "anchor_text": "第 3 页是通信原理常考题型和解析。",
        "source_type": "past_exam",
    } in platform["pdf_evidence_pages"]
    assert platform["pdf_year_signals"] == [{"value": "2024", "count": 1}]
    assert platform["pdf_question_type_signals"] == [{"value": "计算题", "count": 1}]
    assert platform["pdf_chapter_signals"] == [{"value": "第2章 调制解调", "count": 1}]
    assert platform["pdf_solution_signals"] == [{"value": "参考答案", "count": 1}, {"value": "解题步骤", "count": 1}]
    assert platform["pdf_question_number_signals"] == [{"value": "第3题", "count": 1}]
    assert platform["pdf_score_point_signals"] == [{"value": "10", "count": 1}]
    assert platform["pdf_difficulty_signals"] == [{"value": "综合", "count": 1}]
    assert platform["pdf_visual_signals"] == [{"value": "公式", "count": 1}]
    assert platform["pdf_source_type_signals"] == [{"value": "past_exam", "count": 1}]
    assert {"value": "交付信息可用", "count": 3} in platform["material_quality_signals"]
    assert {"value": "高评分资料", "count": 2} in platform["material_quality_signals"]
    assert platform["material_risk_signals"] == [{"value": "简介较短", "count": 1}]
    assert platform["high_signal_materials"][0]["quality_score"] > 0
    assert "quality_signals" in platform["high_signal_materials"][0]
    assert "individual user" in platform["privacy_boundary"]

    user_memory = prompt["user_personal_memory"]
    assert user_memory["profile"] == {"school": "电子科技大学", "college": "信通", "major": "通信", "grade_stages": "大三"}
    assert "private@example.com" not in json.dumps(user_memory, ensure_ascii=False)
    assert "Private Nick" not in json.dumps(user_memory, ensure_ascii=False)
    assert user_memory["candidate_interactions"][0]["signals"] == ["favorited"]
    assert user_memory["candidate_interactions"][1]["signals"] == ["downloaded", "rated_5"]


def test_agent_memory_context_can_be_disabled_and_limits_interaction_checks() -> None:
    material_repo = _FakeMaterialRepo()
    disabled = AgentMemoryService(_settings(ai_agent_memory_context_enabled=False), _FakeAuthRepo(), material_repo)  # type: ignore[arg-type]
    assert disabled.collect(object(), query="通信原理", materials=[], current_user_id=7, pdf_evidence=[]).is_empty()  # type: ignore[arg-type]

    limited = AgentMemoryService(
        _settings(ai_agent_memory_max_materials=2, ai_agent_memory_max_interaction_checks=1),
        _FakeAuthRepo(),
        material_repo,
    )  # type: ignore[arg-type]
    materials = [
        _material(101, title="A 真题", tags=["真题"]),
        _material(102, title="B 解析", tags=["解析"]),
        _material(103, title="C 笔记", tags=["笔记"]),
    ]
    context = limited.collect(object(), query="通信原理", materials=materials, current_user_id=7, pdf_evidence=[])  # type: ignore[arg-type]

    assert context.platform["candidate_count"] == 2
    assert material_repo.checked_downloads == [101]


def test_agent_memory_context_derives_current_query_private_memory() -> None:
    service = AgentMemoryService(_settings(), _FakeAuthRepo(), _FakeMaterialRepo())  # type: ignore[arg-type]

    context = service.collect(
        object(),  # type: ignore[arg-type]
        query="我两周后考试，目标85分，每天2小时，调制和误码率很薄弱，第3题公式推导看不懂，想速成刷题",
        materials=[_material(101, title="通信原理期末速成笔记", tags=["通信原理", "速成"])],
        current_user_id=7,
        pdf_evidence=[],
    )
    prompt = context.to_prompt_payload()

    current_query_memory = prompt["user_personal_memory"]["current_query_memory"]
    assert current_query_memory == {
        "study_constraints": {
            "time_horizon": "两周",
            "days_until_exam": 14,
            "target_score": 85,
            "daily_available_hours": 2.0,
            "weak_points": ["调制", "误码率"],
        },
        "problem_context": {
            "focus_areas": ["概念理解", "公式推导"],
            "question_numbers": ["第3题"],
            "knowledge_points": ["调制", "误码率"],
        },
        "learning_preferences": ["补基础优先", "考前冲刺", "刷题优先", "查漏补缺"],
        "scope": "current_request_only",
        "persistence": "not_persisted",
    }
    assert "current_query_memory" not in json.dumps(prompt["platform_collective_memory"], ensure_ascii=False)
    assert "private@example.com" not in json.dumps(current_query_memory, ensure_ascii=False)
    assert "第3题公式推导看不懂" not in json.dumps(current_query_memory, ensure_ascii=False)


def test_ai_recommendation_prompt_receives_memory_context(monkeypatch) -> None:
    captured: dict[str, Any] = {}

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
            captured["memory_query"] = query
            captured["memory_user_id"] = current_user_id
            return AgentMemoryContext(
                platform={"top_tags": [{"value": "通信原理", "count": 2}]},
                user={
                    "profile": {"school": "电子科技大学", "major": "通信"},
                    "candidate_interactions": [
                        {"material_id": 101, "title": "通信原理四年真题解析", "signals": ["favorited", "downloaded", "rated_5"]},
                    ],
                    "matched_candidate_materials": [
                        {"material_id": 101, "title": "通信原理四年真题解析", "matched_fields": ["major"]},
                    ],
                },
            )

    settings = _settings(
        ai_agent_provider="openai-compatible",
        ai_agent_base_url="https://example.test/v1",
        ai_agent_api_key="test-key",
        ai_agent_model="demo-model",
    )
    monkeypatch.setattr("app.services.ai_service.get_settings", lambda: settings)

    service = AiService(read_repo=None, material_repo=None, memory_service=FakeMemoryService())  # type: ignore[arg-type]
    material = _material(101, title="通信原理四年真题解析", tags=["通信原理", "真题"])
    monkeypatch.setattr(service, "_rank_materials", lambda session, query, filters: [material])

    def fake_call_agent_model(settings: Settings, system_prompt: str, user_prompt: dict[str, Any]) -> str:
        captured["system_prompt"] = system_prompt
        captured["user_prompt"] = user_prompt
        return json.dumps(
            {
                "answer": "已结合记忆上下文推荐通信原理真题。",
                "recommendations": [{"material_id": 101, "reason": "匹配你的通信专业背景"}],
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(service, "_call_agent_model", fake_call_agent_model)

    response = service.recommend(object(), SimpleNamespace(query="通信原理往年题常考什么", filters={}), current_user_id=7)  # type: ignore[arg-type]
    body = json.loads(str(response["output"]).removeprefix("<json>").removesuffix("</json>"))

    assert captured["memory_query"] == "通信原理往年题常考什么"
    assert captured["memory_user_id"] == 7
    assert "memory_context" in captured["user_prompt"]
    assert captured["user_prompt"]["memory_context"]["platform_collective_memory"]["top_tags"][0]["value"] == "通信原理"
    assert captured["user_prompt"]["memory_context"]["user_personal_memory"]["profile"]["major"] == "通信"
    assert captured["user_prompt"]["candidate_materials"][0]["user_fit_signals"] == ["已收藏过", "已下载过", "你给过 5 分", "专业匹配"]
    assert "与你已有学习行为匹配：已收藏过、已下载过、你给过 5 分、专业匹配" in captured["user_prompt"]["candidate_materials"][0]["reason"]
    assert "用户个人记忆" in captured["system_prompt"]
    assert "current_query_memory" in captured["system_prompt"]
    assert body["answer"] == (
        "已结合记忆上下文推荐通信原理真题。 "
        "说明：当前没有可用 PDF 页级证据，这里仅基于候选资料元数据和可见记忆信号给出保守建议。"
    )


def test_ai_local_recommendation_reason_uses_current_user_memory_signals(monkeypatch) -> None:
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
                user={
                    "candidate_interactions": [{"material_id": 101, "title": "通信原理四年真题解析", "signals": ["favorited"]}],
                    "matched_candidate_materials": [{"material_id": 101, "title": "通信原理四年真题解析", "matched_fields": ["major"]}],
                },
            )

    settings = _settings(ai_agent_provider="local")
    monkeypatch.setattr("app.services.ai_service.get_settings", lambda: settings)

    service = AiService(read_repo=None, material_repo=None, memory_service=FakeMemoryService())  # type: ignore[arg-type]
    material = _material(101, title="通信原理四年真题解析", tags=["通信原理", "真题"])
    monkeypatch.setattr(service, "_rank_materials", lambda session, query, filters: [material])

    response = service.recommend(object(), SimpleNamespace(query="通信原理往年题常考什么", filters={}), current_user_id=7)  # type: ignore[arg-type]
    body = json.loads(str(response["output"]).removeprefix("<json>").removesuffix("</json>"))

    assert "user_fit_signals" not in body["recommendations"][0]
    assert "与你已有学习行为匹配：已收藏过、专业匹配" in body["recommendations"][0]["reason"]
