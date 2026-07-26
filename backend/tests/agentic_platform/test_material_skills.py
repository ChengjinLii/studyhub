from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.agentic_platform.skills.context import SkillExecutionContext, SkillExecutionMode
from app.agentic_platform.skills.executor import FixtureSkillExecutor, LiveSkillExecutor, SkillPermissionDeniedError
from app.agentic_platform.skills.registry import build_default_skill_registry
from app.models.materials import MaterialRecord
from app.services.material_pdf_evidence_service import MaterialPageEvidence


MATERIAL_SCOPES = frozenset({"agentic.admin", "materials.read"})


def _material(material_id: int, title: str) -> MaterialRecord:
    return MaterialRecord(
        id=material_id,
        source="local",
        title=title,
        description=f"{title} 的资料说明",
        is_free=True,
        status="VISIBLE",
        tags_json='["真题","通信"]',
        rating_avg=4.5,
        rating_count=4,
        download_count=21,
        like_count=12,
        preview_status="done",
        review_status="APPROVED",
        file_type="pdf",
        file_storage_key=f"materials/{material_id}.pdf",
    )


@dataclass
class FakeMaterialRepository:
    materials: list[MaterialRecord]

    def list_materials_by_ids(self, session: object, material_ids: list[int]) -> list[MaterialRecord]:
        del session
        by_id = {material.id: material for material in self.materials}
        return [by_id[material_id] for material_id in material_ids if material_id in by_id]


@dataclass
class FakeMaterialsService:
    items: list[dict[str, Any]]
    calls: list[dict[str, Any]] = field(default_factory=list)

    def list_materials(self, session: object, current_user_id: int, **kwargs: Any) -> dict[str, Any]:
        del session, current_user_id
        self.calls.append(kwargs)
        return {"items": self.items}


@dataclass
class FakePdfEvidenceService:
    evidence: list[MaterialPageEvidence]
    calls: list[dict[str, Any]] = field(default_factory=list)

    def collect_for_materials(
        self,
        materials: list[MaterialRecord],
        query: str,
        **kwargs: Any,
    ) -> list[MaterialPageEvidence]:
        self.calls.append({"materials": materials, "query": query, **kwargs})
        return self.evidence[: int(kwargs["max_results"])]


def _pdf_evidence() -> list[MaterialPageEvidence]:
    return [
        MaterialPageEvidence(
            material_id=1,
            title="通信原理真题",
            page=3,
            text="2024 年通信原理计算题 第1题，10分。",
            score=20,
            question_types=("计算题",),
            question_numbers=("第1题",),
            source_type="past_exam",
            anchor_terms=("计算题",),
        ),
        MaterialPageEvidence(
            material_id=1,
            title="通信原理真题",
            page=4,
            text="第1题参考答案与解题步骤。",
            score=18,
            question_numbers=("第1题",),
            source_type="answer_explanation",
            solution_signals=("参考答案", "解题步骤"),
            anchor_terms=("参考答案",),
        ),
    ]


def _live_context(
    *,
    repository: FakeMaterialRepository,
    materials_service: FakeMaterialsService,
    pdf_service: FakePdfEvidenceService,
    role_mask: int = 8,
) -> SkillExecutionContext:
    return SkillExecutionContext(
        admin_actor_id=3,
        current_user_id=7,
        role_mask=role_mask,
        current_user_role_mask=role_mask,
        permission_scopes=MATERIAL_SCOPES,
        session=object(),  # Fakes only assert that a session was passed through.
        material_repo=repository,  # type: ignore[arg-type]
        materials_service=materials_service,  # type: ignore[arg-type]
        pdf_evidence_service=pdf_service,  # type: ignore[arg-type]
        mode=SkillExecutionMode.LIVE,
    )


def test_live_material_skills_reuse_services_and_preserve_pdf_pages_and_acl() -> None:
    material = _material(1, "通信原理真题")
    repository = FakeMaterialRepository([material])
    materials_service = FakeMaterialsService(
        [
            {
                "id": 1,
                "title": "通信原理真题",
                "description": "历年计算题",
                "tags": ["真题", "通信"],
                "free": True,
                "ratingAvg": 4.5,
                "ratingCount": 4,
                "downloadCount": 21,
            }
        ]
    )
    pdf_service = FakePdfEvidenceService(_pdf_evidence())
    context = _live_context(repository=repository, materials_service=materials_service, pdf_service=pdf_service)
    executor = LiveSkillExecutor(build_default_skill_registry())

    search = asyncio.run(executor.execute(skill_name="materials.search", arguments={"query": "通信原理", "limit": 3}, context=context))
    inspect = asyncio.run(executor.execute(skill_name="materials.inspect", arguments={"material_ids": [1, 99]}, context=context))
    pdf = asyncio.run(
        executor.execute(
            skill_name="materials.read_pdf_evidence",
            arguments={"material_ids": [1], "query": "计算题", "page_numbers": [3], "max_pages": 2},
            context=context,
        )
    )
    questions = asyncio.run(
        executor.execute(
            skill_name="materials.find_question_pages",
            arguments={"material_ids": [1], "query": "计算题", "max_pages": 2},
            context=context,
        )
    )
    answers = asyncio.run(
        executor.execute(
            skill_name="materials.find_answer_pages",
            arguments={"material_ids": [1], "query": "答案", "max_pages": 2},
            context=context,
        )
    )
    comparison = asyncio.run(executor.execute(skill_name="materials.compare", arguments={"material_ids": [1, 99]}, context=context))

    assert search.output.materials[0].material_id == 1
    assert materials_service.calls[0]["keyword"] == "通信原理"
    assert inspect.output.missing_material_ids == [99]
    assert [item.page for item in pdf.output.evidence] == [3, 4]
    assert pdf_service.calls[0]["current_user_role_mask"] == 8
    assert pdf_service.calls[0]["page_numbers"] == {3}
    assert [item.page for item in questions.output.pages] == [3]
    assert [item.page for item in answers.output.pages] == [4]
    assert comparison.output.comparisons[0].material_id == 1
    assert comparison.output.missing_material_ids == [99]


def test_material_skills_return_typed_empty_results_and_deny_non_admin_before_pdf_access() -> None:
    repository = FakeMaterialRepository([])
    materials_service = FakeMaterialsService([])
    pdf_service = FakePdfEvidenceService(_pdf_evidence())
    context = _live_context(repository=repository, materials_service=materials_service, pdf_service=pdf_service)
    executor = LiveSkillExecutor(build_default_skill_registry())

    search = asyncio.run(executor.execute(skill_name="materials.search", arguments={"query": "不存在"}, context=context))
    inspect = asyncio.run(executor.execute(skill_name="materials.inspect", arguments={"material_ids": [99]}, context=context))
    evidence = asyncio.run(
        executor.execute(
            skill_name="materials.read_pdf_evidence",
            arguments={"material_ids": [99], "query": "题目"},
            context=context,
        )
    )
    comparison = asyncio.run(executor.execute(skill_name="materials.compare", arguments={"material_ids": [98, 99]}, context=context))

    assert search.output.materials == []
    assert inspect.output.materials == []
    assert inspect.output.missing_material_ids == [99]
    assert evidence.output.available is False
    assert evidence.output.evidence == []
    assert comparison.output.comparisons == []
    assert pdf_service.calls == []

    denied_context = _live_context(
        repository=repository,
        materials_service=materials_service,
        pdf_service=pdf_service,
        role_mask=1,
    )
    with pytest.raises(SkillPermissionDeniedError):
        asyncio.run(
            executor.execute(
                skill_name="materials.read_pdf_evidence",
                arguments={"material_ids": [99], "query": "题目"},
                context=denied_context,
            )
        )
    assert pdf_service.calls == []


def test_live_and_fixture_material_search_share_the_same_output_schema() -> None:
    material = _material(1, "通信原理真题")
    repository = FakeMaterialRepository([material])
    materials_service = FakeMaterialsService(
        [{"id": 1, "title": "通信原理真题", "free": True, "ratingAvg": 4.5, "ratingCount": 4, "downloadCount": 21}]
    )
    pdf_service = FakePdfEvidenceService([])
    live = LiveSkillExecutor(build_default_skill_registry())
    live_result = asyncio.run(
        live.execute(
            skill_name="materials.search",
            arguments={"query": "通信原理"},
            context=_live_context(repository=repository, materials_service=materials_service, pdf_service=pdf_service),
        )
    )
    fixture = FixtureSkillExecutor(build_default_skill_registry())
    fixture_result = asyncio.run(
        fixture.execute(
            skill_name="materials.search",
            arguments={"query": "通信原理"},
            context=SkillExecutionContext(
                admin_actor_id=3,
                role_mask=8,
                permission_scopes=MATERIAL_SCOPES,
                mode=SkillExecutionMode.FIXTURE,
                fixture_outputs={
                    "materials.search": {
                        "query": "通信原理",
                        "materials": [],
                        "retrieval_engine": "fixture",
                        "count": 0,
                    }
                },
            ),
        )
    )

    assert type(live_result.output) is type(fixture_result.output)
    assert type(live_result.output).model_json_schema() == type(fixture_result.output).model_json_schema()
