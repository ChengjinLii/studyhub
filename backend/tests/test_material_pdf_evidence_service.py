from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from app.models.materials import MaterialRecord
from app.services.ai_service import AiService
from app.services.material_pdf_evidence_service import (
    MaterialPageEvidence,
    MaterialPdfEvidenceService,
    build_pdf_page_chunks,
    extract_pdf_page_texts,
)


def _settings(**overrides: Any) -> SimpleNamespace:
    values = {
        "ai_agent_pdf_evidence_enabled": True,
        "ai_agent_pdf_evidence_max_materials": 2,
        "ai_agent_pdf_evidence_max_pages": 3,
        "ai_agent_pdf_evidence_max_bytes": 4096,
        "ai_agent_pdf_extract_cache_enabled": True,
        "ai_agent_pdf_extract_cache_max_entries": 64,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _material(
    *,
    material_id: int = 1,
    title: str = "通信原理往年真题解析",
    free: bool = True,
    uploader_id: int | None = 7,
    key: str | None = "materials/demo.pdf",
    file_type: str | None = "pdf",
) -> MaterialRecord:
    return MaterialRecord(
        id=material_id,
        title=title,
        description="通信原理期末考试资料",
        is_free=free,
        uploader_id=uploader_id,
        file_storage_key=key,
        original_filename="demo.pdf",
        file_type=file_type,
        tags_json=json.dumps(["通信原理", "真题"], ensure_ascii=False),
        download_count=0,
    )


class _FakeAssetStore:
    def __init__(self, payload: bytes | None = None) -> None:
        if payload is None:
            payload = "%PDF /Type /Page (通信原理 真题 解析 常考题型)".encode()
        self.payload = payload
        self.read_keys: list[str] = []
        self.max_size_bytes: list[int] = []

    def read_bytes(self, key: str, *, max_size_bytes: int) -> bytes:
        self.read_keys.append(key)
        self.max_size_bytes.append(max_size_bytes)
        return self.payload


def test_extract_pdf_page_texts_uses_safe_literal_fallback_for_simple_pdf_bytes() -> None:
    pages = extract_pdf_page_texts(
        "%PDF-1.4\n1 0 obj << /Type /Page >> stream (通信原理 真题 解析 常考题型) endstream".encode(),
        max_pages=2,
    )

    assert pages == [(1, "通信原理 真题 解析 常考题型")]


def test_build_pdf_page_chunks_extracts_year_question_type_and_knowledge_signals() -> None:
    chunks = build_pdf_page_chunks(
        "%PDF-1.4\n1 0 obj << /Type /Page >> stream (第2章 调制解调。2024 通信原理 真题 第3题 计算题 10分 综合题 较难 公式 推导 如图 表格 调制 解调 误码率 参考答案 解题步骤 评分标准 易错) endstream".encode(),
        max_pages=2,
    )

    assert len(chunks) == 1
    assert chunks[0].page == 1
    assert chunks[0].years == ("2024",)
    assert "计算题" in chunks[0].question_types
    assert "调制" in chunks[0].knowledge_signals
    assert chunks[0].question_numbers == ("第3题",)
    assert chunks[0].chapter_signals == ("第2章 调制解调",)
    assert chunks[0].solution_signals == ("参考答案", "解题步骤", "评分标准", "易错点")
    assert chunks[0].source_type == "answer_explanation"
    assert chunks[0].score_points == (10,)
    assert chunks[0].difficulty_signals == ("综合", "偏难")
    assert chunks[0].visual_signals == ("公式", "图示", "表格", "图片题")


def test_build_pdf_page_chunks_filters_unreadable_extracted_text() -> None:
    readable_chunks = build_pdf_page_chunks(
        "%PDF-1.4\n1 0 obj << /Type /Page >> stream (2024 通信原理 真题 第3题 计算题 10分 参考答案 解题步骤) endstream".encode(),
        max_pages=2,
    )
    garbled_chunks = build_pdf_page_chunks(
        "%PDF-1.4\n1 0 obj << /Type /Page >> stream (ն࿐໾৘ཿᄝభ૫ճีඨ྽๭ཞჰ৘ҰѯᄸဢԮѬᄸဢᄝཌྷ໊ҵ৚ཁԛ่໕) endstream".encode(),
        max_pages=2,
    )

    assert len(readable_chunks) == 1
    assert garbled_chunks == []


def test_pdf_evidence_only_loads_for_study_queries_and_respects_file_limit() -> None:
    store = _FakeAssetStore()
    service = MaterialPdfEvidenceService(_settings(ai_agent_pdf_evidence_max_bytes=32), store)  # type: ignore[arg-type]

    assert service.collect_for_materials([_material()], "随便看看资料", current_user_id=7) == []
    assert store.read_keys == []
    assert service.should_load_evidence("这份资料讲什么")
    assert service.should_load_evidence("这道题不会怎么做")
    assert service.should_load_evidence("通信原理讲义适合我吗")

    evidence = service.collect_for_materials([_material()], "通信原理往年真题常考题型", current_user_id=7)

    assert len(evidence) == 1
    assert evidence[0].material_id == 1
    assert evidence[0].page == 1
    assert "通信原理" in evidence[0].text
    assert evidence[0].anchor_terms == ("真题",)
    assert evidence[0].anchor_text == "通信原理 真题 解析 常考题型"
    assert store.read_keys == ["materials/demo.pdf"]
    assert store.max_size_bytes == [32]


def test_pdf_evidence_caches_only_free_material_extractions() -> None:
    store = _FakeAssetStore()
    service = MaterialPdfEvidenceService(_settings(), store)  # type: ignore[arg-type]

    free_material = _material(free=True)
    service.collect_for_material(free_material, "通信原理真题")
    service.collect_for_material(free_material, "通信原理真题")
    assert store.read_keys == ["materials/demo.pdf"]

    paid_material = _material(material_id=2, free=False, key="materials/paid.pdf")
    service.collect_for_material(paid_material, "通信原理真题")
    service.collect_for_material(paid_material, "通信原理真题")
    assert store.read_keys == ["materials/demo.pdf", "materials/paid.pdf", "materials/paid.pdf"]


def test_pdf_evidence_skips_paid_material_when_user_does_not_own_it() -> None:
    store = _FakeAssetStore()
    service = MaterialPdfEvidenceService(_settings(), store)  # type: ignore[arg-type]

    evidence = service.collect_for_materials(
        [_material(free=False, uploader_id=7)],
        "通信原理真题常考什么",
        current_user_id=8,
    )

    assert evidence == []
    assert store.read_keys == []


def test_pdf_evidence_allows_paid_material_for_admin_role() -> None:
    store = _FakeAssetStore()
    service = MaterialPdfEvidenceService(_settings(), store)  # type: ignore[arg-type]

    evidence = service.collect_for_materials(
        [_material(free=False, uploader_id=7)],
        "通信原理真题常考什么",
        current_user_id=8,
        current_user_role_mask=8,
    )

    assert len(evidence) == 1
    assert store.read_keys == ["materials/demo.pdf"]


def test_pdf_evidence_allows_paid_material_uploaded_by_current_user() -> None:
    store = _FakeAssetStore()
    service = MaterialPdfEvidenceService(_settings(), store)  # type: ignore[arg-type]

    evidence = service.collect_for_materials(
        [_material(free=False, uploader_id=7)],
        "通信原理真题常考什么",
        current_user_id=7,
    )

    assert len(evidence) == 1
    assert store.read_keys == ["materials/demo.pdf"]


def test_pdf_evidence_missing_file_key_does_not_consume_scan_budget() -> None:
    store = _FakeAssetStore()
    service = MaterialPdfEvidenceService(_settings(ai_agent_pdf_evidence_max_materials=1), store)  # type: ignore[arg-type]

    evidence = service.collect_for_materials(
        [
            _material(material_id=1, key=None),
            _material(material_id=2, key="materials/second.pdf"),
        ],
        "通信原理真题常考什么",
        current_user_id=7,
    )

    assert len(evidence) == 1
    assert evidence[0].material_id == 2
    assert store.read_keys == ["materials/second.pdf"]


def test_pdf_evidence_prompt_payload_has_stable_internal_provenance() -> None:
    evidence = MaterialPageEvidence(
        material_id=1,
        title="通信原理往年真题解析",
        page=2,
        text="通信原理真题第 2 页包含调制解调常考题。",
        score=20,
        years=("2024",),
        question_types=("计算题",),
        knowledge_signals=("调制", "解调"),
        question_numbers=("第3题",),
        source_type="past_exam",
        anchor_terms=("第3题", "计算题"),
        anchor_text="第 2 页包含调制解调常考题。",
    )
    same = MaterialPageEvidence(
        material_id=1,
        title="通信原理往年真题解析",
        page=2,
        text="通信原理真题第 2 页包含调制解调常考题。",
        score=99,
        years=("2024",),
        question_types=("计算题",),
        knowledge_signals=("调制", "解调"),
        question_numbers=("第3题",),
        source_type="past_exam",
        anchor_terms=("第3题", "计算题"),
        anchor_text="第 2 页包含调制解调常考题。",
    )
    changed = MaterialPageEvidence(
        material_id=1,
        title="通信原理往年真题解析",
        page=3,
        text="通信原理真题第 3 页包含误码率常考题。",
        score=20,
        years=("2024",),
        question_types=("计算题",),
        knowledge_signals=("误码率",),
        question_numbers=("第4题",),
        source_type="past_exam",
    )

    payload = evidence.to_prompt_payload()

    assert payload["schema"] == "material-page-evidence-v1"
    assert len(payload["evidence_id"]) == 16
    assert payload["evidence_id"] == same.to_prompt_payload()["evidence_id"]
    assert payload["evidence_id"] != changed.to_prompt_payload()["evidence_id"]
    assert payload["provenance"] == {
        "source": "pdf_page_chunk",
        "persistence": "not_persisted",
        "cacheScope": "bounded_in_memory_for_free_materials",
    }
    source_payload = evidence.to_source_payload()
    assert "schema" not in source_payload
    assert "evidence_id" not in source_payload
    assert "provenance" not in source_payload


def test_ai_recommendation_response_includes_pdf_evidence_sources(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    class FakePdfEvidenceService:
        def collect_for_materials(
            self,
            materials: list[MaterialRecord],
            query: str,
            *,
            current_user_id: int | None,
        ) -> list[MaterialPageEvidence]:
            captured["materials"] = materials
            captured["query"] = query
            captured["current_user_id"] = current_user_id
            return [
                MaterialPageEvidence(
                    material_id=materials[0].id,
                    title=materials[0].title,
                    page=2,
                    text="通信原理真题第 2 页包含调制解调常考题。",
                    score=20,
                    years=("2024",),
                    question_types=("计算题",),
                    knowledge_signals=("调制", "解调"),
                    question_numbers=("第3题",),
                    source_type="past_exam",
                    score_points=(10,),
                    difficulty_signals=("综合",),
                    visual_signals=("公式",),
                )
            ]

    service = AiService(read_repo=None, material_repo=None, pdf_evidence_service=FakePdfEvidenceService())  # type: ignore[arg-type]
    material = _material()
    monkeypatch.setattr(service, "_rank_materials", lambda session, query, filters: [material])
    monkeypatch.setattr(
        service,
        "_generate_agent_recommendation",
        lambda query, materials, *, conversation_context, pdf_evidence, memory_context, query_plan, course_memory_card: None,
    )

    response = service.recommend(object(), SimpleNamespace(query="通信原理往年题常考什么", filters={}), current_user_id=7)  # type: ignore[arg-type]
    raw_output = response["output"]
    assert isinstance(raw_output, str)
    body = json.loads(raw_output.removeprefix("<json>").removesuffix("</json>"))

    assert captured["query"] == "通信原理往年题常考什么"
    assert captured["current_user_id"] == 7
    assert body["evidence_sources"] == [
        {
            "material_id": 1,
            "title": "通信原理往年真题解析",
            "page": 2,
            "excerpt": "通信原理真题第 2 页包含调制解调常考题。",
            "years": ["2024"],
            "question_types": ["计算题"],
            "question_numbers": ["第3题"],
            "source_type": "past_exam",
        }
    ]
    assert "score_points" not in body["evidence_sources"][0]
    assert "difficulty_signals" not in body["evidence_sources"][0]
    assert "anchor_terms" not in body["evidence_sources"][0]
    assert "anchor_text" not in body["evidence_sources"][0]
    assert "第 2 页" in body["answer"]
    assert "年份信号包括 2024" in body["answer"]
    assert "题型集中在 计算题" in body["answer"]
    assert "高频知识点包括 调制、解调" in body["answer"]
    assert "分值信号包括 10分" in body["answer"]
    assert "难度信号包括 综合" in body["answer"]
    assert "需关注的公式/图表信号包括 公式" in body["answer"]
