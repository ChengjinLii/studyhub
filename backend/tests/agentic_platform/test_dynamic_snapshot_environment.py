from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from app.agentic_platform.deepresearch.state import ResearchSourceType, ResearchTaskPacket, initial_research_state
from app.agentic_platform.domain.decision import AgentActionType, AgentDecision, ExpectedStateChange
from app.agentic_platform.domain.state import ConstraintState
from app.agentic_platform.simulation.clock import ClockState
from app.agentic_platform.simulation.environment import SnapshotStudyHubEnvironment
from app.agentic_platform.simulation.scenario import ScenarioSpec
from app.agentic_platform.simulation.snapshot_skill_executor import SnapshotEnvironmentActionExecutor, SnapshotSkillExecutor
from app.agentic_platform.simulation.world_snapshot import (
    CatalogSplit,
    InMemoryWorldSnapshotArtifactStore,
    SnapshotCatalog,
    SnapshotDataLeakageError,
    SnapshotMaterial,
    SnapshotPdfPage,
    SnapshotPdfPageIndex,
    SnapshotPermissionRecord,
    SnapshotPermissionState,
    SnapshotRetrieverEntry,
    SnapshotRetrieverIndex,
    StudyHubWorldSnapshotBuilder,
)
from app.agentic_platform.skills.context import SkillExecutionContext, SkillExecutionMode
from app.agentic_platform.skills.registry import build_default_skill_registry
from app.services.read_support import ROLE_ADMIN
from tests.agentic_platform.factories import task_state


BASE_TIME = datetime(2026, 7, 27, 0, 0, tzinfo=UTC)


def _snapshot(*, restricted_material_allowed: bool = False):
    artifact_store = InMemoryWorldSnapshotArtifactStore()
    catalog = SnapshotCatalog(
        split=CatalogSplit.TRAIN,
        items=[
            SnapshotMaterial(
                material_id=1,
                title="Calculus derivatives notes",
                description="Derivative rules and worked calculus examples.",
                tags=["calculus", "derivatives"],
                course_category="math",
                rating_avg=4.8,
                rating_count=12,
                download_count=25,
                quality_signals=["worked_examples"],
                observed_at=BASE_TIME,
            ),
            SnapshotMaterial(
                material_id=2,
                title="Linear algebra matrix workbook",
                description="Matrices, vectors, and linear transformations.",
                tags=["linear-algebra", "matrices"],
                course_category="math",
                rating_avg=4.5,
                rating_count=8,
                download_count=14,
                observed_at=BASE_TIME,
            ),
            SnapshotMaterial(
                material_id=3,
                title="Restricted advanced analysis",
                description="Restricted material that must honor the frozen ACL.",
                tags=["analysis"],
                observed_at=BASE_TIME,
            ),
            SnapshotMaterial(
                material_id=4,
                title="Corrupt PDF fixture",
                description="A catalog item whose frozen PDF evidence is corrupt.",
                tags=["corrupt"],
                observed_at=BASE_TIME,
            ),
        ],
    )
    pages = SnapshotPdfPageIndex(
        pages=[
            SnapshotPdfPage(
                material_id=1,
                page=2,
                title="Calculus derivatives notes",
                excerpt="The derivative of x squared is two x.",
                question_types=["calculation"],
                anchor_terms=["derivative", "calculus"],
            ),
            SnapshotPdfPage(
                material_id=2,
                page=5,
                title="Linear algebra matrix workbook",
                excerpt="Matrix multiplication composes linear transformations.",
                question_types=["proof"],
                anchor_terms=["matrix", "linear algebra"],
            ),
            SnapshotPdfPage(
                material_id=4,
                page=1,
                title="Corrupt PDF fixture",
                excerpt=None,
                corrupt=True,
            ),
        ]
    )
    permissions = SnapshotPermissionState(
        records=[
            SnapshotPermissionRecord(material_id=1, allowed=True),
            SnapshotPermissionRecord(material_id=2, allowed=True),
            SnapshotPermissionRecord(material_id=3, allowed=restricted_material_allowed, reason_code="frozen_restricted_acl"),
            SnapshotPermissionRecord(material_id=4, allowed=True),
        ]
    )
    retriever = SnapshotRetrieverIndex(
        retriever_version="fixture-retriever-v1",
        entries=[
            SnapshotRetrieverEntry(material_id=1, terms=["calculus", "derivative", "differentiation"]),
            SnapshotRetrieverEntry(material_id=2, terms=["linear", "algebra", "matrix"]),
            SnapshotRetrieverEntry(material_id=3, terms=["analysis"]),
            SnapshotRetrieverEntry(material_id=4, terms=["corrupt"]),
        ],
    )
    snapshot = StudyHubWorldSnapshotBuilder(artifact_store).build(
        catalog=catalog,
        pdf_page_index=pages,
        permissions=permissions,
        retriever=retriever,
        clock_state=ClockState(started_at=BASE_TIME, tick_seconds=60),
        random_seed=73,
        source_commit_sha="abcdef123456",
        catalog_cutoff_at=BASE_TIME,
        learner_state={"stage": "synthetic"},
        user_simulator_state={"persona": "synthetic"},
    )
    return snapshot, artifact_store


def _context(registry) -> SkillExecutionContext:
    return SkillExecutionContext(
        admin_actor_id=3,
        role_mask=ROLE_ADMIN,
        permission_scopes=frozenset(scope for skill in registry.list() for scope in skill.spec.permission_scopes),
        mode=SkillExecutionMode.SNAPSHOT,
    )


def _action(skill_name: str, arguments: dict[str, object]) -> AgentDecision:
    return AgentDecision(
        action_type=AgentActionType.EXECUTE_SKILL,
        plan_step_id="snapshot-step",
        rationale_summary=f"Execute the policy-selected {skill_name} against the frozen snapshot.",
        expected_state_change=ExpectedStateChange(summary="Record a deterministic snapshot observation."),
        skill_name=skill_name,
        arguments=arguments,
    )


def test_dynamic_snapshot_skill_executor_supports_distinct_legal_queries_without_action_scripts() -> None:
    snapshot, artifact_store = _snapshot()
    registry = build_default_skill_registry()
    first = SnapshotSkillExecutor(registry, snapshot=snapshot, artifact_store=artifact_store)
    second = SnapshotSkillExecutor(registry, snapshot=snapshot, artifact_store=artifact_store)

    calculus = asyncio.run(first.execute(skill_name="materials.search", arguments={"query": "calculus"}, context=_context(registry)))
    algebra = asyncio.run(first.execute(skill_name="materials.search", arguments={"query": "linear algebra"}, context=_context(registry)))
    rewritten = asyncio.run(second.execute(skill_name="materials.search", arguments={"query": "calculus derivatives"}, context=_context(registry)))
    repeat = asyncio.run(second.execute(skill_name="materials.search", arguments={"query": "calculus"}, context=_context(registry)))

    assert [item.material_id for item in calculus.output.materials] == [1]
    assert [item.material_id for item in algebra.output.materials] == [2]
    assert [item.material_id for item in rewritten.output.materials] == [1]
    assert repeat.output.model_dump(mode="json") == calculus.output.model_dump(mode="json")


def test_snapshot_handles_invalid_material_permission_and_corrupt_pdf_fixtures_deterministically() -> None:
    snapshot, artifact_store = _snapshot()
    registry = build_default_skill_registry()
    executor = SnapshotSkillExecutor(registry, snapshot=snapshot, artifact_store=artifact_store)
    context = _context(registry)

    inspected = asyncio.run(
        executor.execute(
            skill_name="materials.inspect",
            arguments={"material_ids": [1, 3, 999]},
            context=context,
        )
    )
    corrupt = asyncio.run(
        executor.execute(
            skill_name="materials.read_pdf_evidence",
            arguments={"material_ids": [4], "query": "corrupt pdf"},
            context=context,
        )
    )
    task = ResearchTaskPacket(
        task_id="snapshot-research",
        admin_actor_id=3,
        research_question="Find calculus evidence.",
        allowed_source_types=[ResearchSourceType.INTERNAL_MATERIAL],
    )
    research_state = initial_research_state(task)
    denied = asyncio.run(
        executor.execute(
            skill_name="research.read_internal",
            arguments={"state": research_state.model_dump(mode="json"), "source_ids": ["material:3"]},
            context=context,
        )
    )

    assert [item.material_id for item in inspected.output.materials] == [1]
    assert inspected.output.missing_material_ids == [3, 999]
    assert corrupt.output.available is False
    assert corrupt.output.reason == "pdf_corrupt"
    assert denied.output.error_code == "permission_denied"


def test_snapshot_research_and_validation_skills_use_frozen_data_not_live_services() -> None:
    snapshot, artifact_store = _snapshot()
    registry = build_default_skill_registry()
    executor = SnapshotSkillExecutor(registry, snapshot=snapshot, artifact_store=artifact_store)
    context = _context(registry)
    research_state = initial_research_state(
        ResearchTaskPacket(
            task_id="snapshot-research-search",
            admin_actor_id=3,
            research_question="Find matrix evidence.",
            allowed_source_types=[ResearchSourceType.INTERNAL_MATERIAL],
        )
    )

    search = asyncio.run(
        executor.execute(
            skill_name="research.search_internal",
            arguments={"state": research_state.model_dump(mode="json"), "query": "matrix"},
            context=context,
        )
    )
    validation = asyncio.run(
        executor.execute(
            skill_name="validation.check_constraints",
            arguments={
                "constraints": [ConstraintState(constraint_id="c1", description="Use verified evidence").model_dump(mode="json")],
                "claimed_resolved_constraint_ids": [],
            },
            context=context,
        )
    )

    assert [source.source_id for source in search.output.delta.sources_to_add] == ["material:2"]
    assert validation.output.valid is True


def test_snapshot_environment_replays_same_seed_action_but_accepts_a_different_legal_action() -> None:
    snapshot, artifact_store = _snapshot()
    registry = build_default_skill_registry()
    action_executor = SnapshotEnvironmentActionExecutor(registry, snapshot=snapshot, artifact_store=artifact_store)
    scenario = ScenarioSpec(
        scenario_id="dynamic-snapshot",
        initial_snapshot=snapshot.as_environment_snapshot(task_state()),
    )
    calculus = _action("materials.search", {"query": "calculus"})
    algebra = _action("materials.search", {"query": "linear algebra"})

    async def rollout(action: AgentDecision):
        environment = SnapshotStudyHubEnvironment(action_executor)
        await environment.reset(scenario, seed=73)
        return await environment.step(action)

    first = asyncio.run(rollout(calculus))
    repeat = asyncio.run(rollout(calculus))
    different = asyncio.run(rollout(algebra))

    assert first.state_after_hash == repeat.state_after_hash
    assert first.observation is not None and repeat.observation is not None
    assert first.observation.model_dump(mode="json") == repeat.observation.model_dump(mode="json")
    assert first.state.working_set.candidate_ids == ["material:1"]
    assert different.error is None
    assert different.state.working_set.candidate_ids == ["material:2"]
    assert different.state_after_hash != first.state_after_hash


def test_world_snapshot_rejects_future_or_forbidden_data_before_execution() -> None:
    artifact_store = InMemoryWorldSnapshotArtifactStore()
    catalog = SnapshotCatalog(
        split=CatalogSplit.TEST,
        items=[
            SnapshotMaterial(
                material_id=1,
                title="Future catalog row",
                observed_at=datetime(2026, 7, 28, tzinfo=UTC),
            )
        ],
    )
    builder = StudyHubWorldSnapshotBuilder(artifact_store)
    kwargs = {
        "catalog": catalog,
        "pdf_page_index": SnapshotPdfPageIndex(),
        "permissions": SnapshotPermissionState(records=[SnapshotPermissionRecord(material_id=1, allowed=True)]),
        "retriever": SnapshotRetrieverIndex(retriever_version="fixture", entries=[]),
        "clock_state": ClockState(started_at=BASE_TIME),
        "random_seed": 1,
        "source_commit_sha": "abcdef1",
        "catalog_cutoff_at": BASE_TIME,
    }
    with pytest.raises(SnapshotDataLeakageError, match="future"):
        builder.build(**kwargs)
    safe_catalog = catalog.model_copy(update={"items": [catalog.items[0].model_copy(update={"observed_at": BASE_TIME})]})
    with pytest.raises(SnapshotDataLeakageError, match="forbidden"):
        builder.build(**(kwargs | {"catalog": safe_catalog, "learner_state": {"future_interactions": ["leak"]}}))
