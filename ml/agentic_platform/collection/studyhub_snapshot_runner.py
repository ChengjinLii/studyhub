"""Trusted local runner for the 100-scenario StudyHub Snapshot Pilot."""

from __future__ import annotations

import os
from pathlib import Path
from time import perf_counter
from typing import Any

from app.agentic_platform.domain import apply_state_delta
from app.agentic_platform.domain.artifact import ArtifactKind
from app.agentic_platform.domain.data_policy import TrainingDataPolicy
from app.agentic_platform.domain.decision import AgentActionType, AgentDecision
from app.agentic_platform.domain.hashing import canonical_hash, canonical_json
from app.agentic_platform.domain.observation import Observation, ObservationSource
from app.agentic_platform.domain.plan import AgentPlan, PlanStep
from app.agentic_platform.domain.reward_facts import RewardFacts
from app.agentic_platform.domain.state import (
    AgentBudget,
    AgentTaskState,
    ConstraintState,
    EnvironmentRef,
    GoalState,
    MilestoneState,
    StateDelta,
    TriggerContext,
    TriggerType,
)
from app.agentic_platform.domain.transition import ExecutionError, VerifierResult
from app.agentic_platform.persistence.durable_transition_sink import DurableTransitionSink
from app.agentic_platform.policy.context_builder import ContextBuilder
from app.agentic_platform.runtime.kernel import AgentKernel, KernelRunStatus
from app.agentic_platform.runtime.nodes import ActionExecutionResult, InMemoryRuntimeArtifactStore, RuntimeMetadata
from app.agentic_platform.simulation.environment import SnapshotStudyHubEnvironment
from app.agentic_platform.simulation.replay import ReplayRequest, SnapshotReplayRunner
from app.agentic_platform.simulation.scenario import ScenarioSpec
from app.agentic_platform.simulation.snapshot_skill_executor import SnapshotEnvironmentActionExecutor, SnapshotSkillExecutor
from app.agentic_platform.skills.context import SkillExecutionContext, SkillExecutionMode
from app.agentic_platform.skills.executor import SkillExecutionError
from app.agentic_platform.skills.registry import SkillRegistry, build_default_skill_registry
from app.services.read_support import ROLE_ADMIN

from .offline_guard import assert_offline_pilot_environment
from .snapshot_pilot_data import build_synthetic_world_snapshot
from .snapshot_pilot_policy import (
    FixtureSnapshotRouterProvider,
    PilotObservationLedger,
    StudyHubSnapshotPolicy,
    final_has_refusal,
    local_qwen_provider,
)


DEFAULT_MODEL_PATH = Path("/data/chengjin/studyhub/models/P0/Qwen3.5-2B")
DEFAULT_ADAPTER_PATH = Path(
    "/data/chengjin/studyhub/training_artifacts/studyhub_agent_sft/qwen35_2b_lora_v1_3_state_ablation_from_7703"
)


class SnapshotRuntimeSkillExecutor:
    """Execute typed Snapshot Skills while preserving kernel working-set state."""

    def __init__(
        self,
        *,
        registry: SkillRegistry,
        snapshot,
        world_artifact_store,
        runtime_artifact_store: InMemoryRuntimeArtifactStore,
        ledger: PilotObservationLedger,
        seed: int,
    ) -> None:
        self.registry = registry
        self.executor = SnapshotSkillExecutor(
            registry,
            snapshot=snapshot,
            artifact_store=world_artifact_store,
            seed=seed,
        )
        self.runtime_artifact_store = runtime_artifact_store
        self.ledger = ledger
        self.permission_scopes = frozenset(scope for skill in registry.list() for scope in skill.spec.permission_scopes)

    async def execute(
        self,
        state: AgentTaskState,
        decision: AgentDecision,
        *,
        idempotency_key: str,
    ) -> ActionExecutionResult:
        if decision.skill_name is None or decision.arguments is None:
            raise ValueError("snapshot Skill decisions require a name and arguments")
        context = SkillExecutionContext(
            admin_actor_id=state.admin_actor_id,
            role_mask=ROLE_ADMIN,
            permission_scopes=self.permission_scopes,
            idempotency_key=idempotency_key,
            current_user_id=state.admin_actor_id,
            current_user_role_mask=ROLE_ADMIN,
            mode=SkillExecutionMode.SNAPSHOT,
        )
        try:
            result = await self.executor.execute(
                skill_name=decision.skill_name,
                arguments=decision.arguments,
                context=context,
            )
            output = result.output.model_dump(mode="json")
            reference = await self.runtime_artifact_store.store_json(
                state,
                artifact_type=ArtifactKind.OBSERVATION,
                artifact_key=f"snapshot-skill:{decision.skill_name}",
                payload=output,
                summary=f"Frozen typed output from {decision.skill_name}",
                idempotency_key=f"snapshot-observation:{idempotency_key}",
            )
            self.ledger.record(decision.skill_name, output)
            candidate_ids = [f"material:{material_id}" for material_id in _candidate_ids(output)]
            evidence_count = len(output.get("evidence", [])) if isinstance(output.get("evidence"), list) else 0
            return ActionExecutionResult(
                state_delta=StateDelta(
                    candidate_ids_to_add=candidate_ids,
                    evidence_refs_to_add=[reference] if evidence_count else [],
                    artifact_refs_to_add=[reference],
                ),
                observation=Observation(
                    observation_id=f"snapshot_observation_{canonical_hash({'run': state.run_id, 'key': idempotency_key})[:30]}",
                    source=ObservationSource.SKILL,
                    summary=f"Snapshot Skill {decision.skill_name} returned a schema-valid frozen observation.",
                    artifact_ref=reference,
                ),
                verifier_result=VerifierResult(passed=True, summary="Snapshot Skill output is schema-valid."),
                reward_facts=RewardFacts(evidence_added=evidence_count, tool_cost=result.estimated_cost),
                estimated_cost=result.estimated_cost,
            )
        except SkillExecutionError as exc:
            return ActionExecutionResult(
                error=ExecutionError(code=exc.code, summary="Snapshot Skill execution failed.", retryable=exc.retryable)
            )


async def run_snapshot_pilot_scenario(
    *,
    scenario: dict[str, object],
    provider: str,
    trajectory_root: str,
    output_dir: str,
) -> dict[str, object]:
    payload = dict(scenario.get("payload") or {})
    scenario_id = str(scenario["scenario_id"])
    seed = int(payload.get("seed") or 73)
    model_path = Path(os.getenv("STUDYHUB_OFFLINE_PILOT_MODEL", str(DEFAULT_MODEL_PATH)))
    adapter_path = Path(os.getenv("STUDYHUB_OFFLINE_PILOT_ADAPTER", str(DEFAULT_ADAPTER_PATH)))
    local_model = provider.lower().startswith("local-qwen")
    assert_offline_pilot_environment(
        provider=provider,
        trajectory_root=trajectory_root,
        output_dir=output_dir,
        model_path=model_path if local_model else None,
        adapter_path=adapter_path if local_model else None,
        artifact_root=os.getenv("STUDYHUB_OFFLINE_PILOT_ROOT") or None,
    )

    source_commit = os.getenv("STUDYHUB_OFFLINE_PILOT_SOURCE_COMMIT", "offline-pilot-uncommitted")
    snapshot, world_artifact_store = build_synthetic_world_snapshot(seed=seed, source_commit_sha=source_commit)
    registry = build_default_skill_registry()
    runtime_artifact_store = InMemoryRuntimeArtifactStore()
    ledger = PilotObservationLedger()
    state = _initial_state(scenario_id=scenario_id, payload=payload, snapshot=snapshot)
    state = await _seed_initial_context(
        state,
        payload=payload,
        ledger=ledger,
        runtime_artifact_store=runtime_artifact_store,
    )
    initial_state = state.model_copy(deep=True)
    constraints_enabled = provider.lower().endswith("guarded")
    router_provider = (
        local_qwen_provider(
            model_path=model_path,
            adapter_path=adapter_path,
            device=os.getenv("STUDYHUB_OFFLINE_PILOT_DEVICE", "cuda:0"),
        )
        if local_model
        else FixtureSnapshotRouterProvider()
    )
    policy = StudyHubSnapshotPolicy(
        scenario=payload,
        ledger=ledger,
        provider=router_provider,
        constraints_enabled=constraints_enabled,
    )
    skill_executor = SnapshotRuntimeSkillExecutor(
        registry=registry,
        snapshot=snapshot,
        world_artifact_store=world_artifact_store,
        runtime_artifact_store=runtime_artifact_store,
        ledger=ledger,
        seed=seed,
    )
    sink = DurableTransitionSink(trajectory_root)
    data_policy = TrainingDataPolicy.model_validate(scenario.get("data_policy"))
    metadata = RuntimeMetadata(
        runtime_version="studyhub-offline-pilot-v1",
        policy_version="qwen35-v1.3-runtime-guarded" if constraints_enabled else "qwen35-v1.3-runtime-raw",
        model_id="Qwen3.5-2B" if local_model else "fixture-snapshot-router-v1",
        model_revision=adapter_path.name if local_model else "dynamic-state-policy",
        skill_catalog_hash=canonical_hash([skill.spec.model_dump(mode="json") for skill in registry.list()], exclude_fields=()),
        retriever_version="studyhub-synthetic-bm25-v1",
        data_policy=data_policy,
    )
    kernel = AgentKernel(
        policy=policy,
        context_builder=ContextBuilder(token_budget=8_000),
        skill_registry=registry,
        skill_action_executor=skill_executor,
        artifact_store=runtime_artifact_store,
        transition_sink=sink,
        model_turn_sink=sink,
        metadata=metadata,
    )
    started = perf_counter()
    try:
        result = await kernel.start(state)
    finally:
        await kernel.close()
    elapsed = perf_counter() - started

    trajectory_id = _trajectory_id(state.thread_id, state.run_id)
    records = None
    try:
        records = sink.load_records(trajectory_id)
    except Exception:  # noqa: BLE001 - terminal failures may stop before the first canonical transition.
        pass
    decisions = [event.parsed_decision for event in records.transitions] if records is not None else list(policy.decisions)
    citation_valid = _citation_valid(payload=payload, final=policy.latest_final, ledger=ledger)
    replay_consistent = await _replay_consistent(
        snapshot=snapshot,
        world_artifact_store=world_artifact_store,
        registry=registry,
        initial_state=initial_state,
        decisions=decisions,
        scenario_id=scenario_id,
        seed=seed,
    )
    violations = _scenario_violations(
        payload=payload,
        result_status=result.status,
        decisions=decisions,
        final=policy.latest_final,
        ledger=ledger,
        citation_valid=citation_valid,
    )
    diagnostic = {
        "schema_version": "1.0",
        "scenario_id": scenario_id,
        "family": payload.get("family"),
        "provider": provider,
        "kernel_status": result.status.value,
        "terminal_reason": result.state.terminal.reason if result.state.terminal is not None else None,
        "remaining_budget": result.state.budget.model_dump(mode="json"),
        "trajectory_id": trajectory_id if records is not None else None,
        "tool_names": [decision.skill_name for decision in decisions if decision.skill_name],
        "final": policy.latest_final,
        "latest_raw_model_output": policy.latest_raw_text,
        "model_failures": list(policy.model_failures),
        "violations": violations,
        "citation_valid": citation_valid,
        "replay_consistent": replay_consistent,
        "elapsed_seconds": elapsed,
        "content_hash": canonical_hash(
            {
                "scenario_id": scenario_id,
                "provider": provider,
                "status": result.status.value,
                "violations": violations,
                "final": policy.latest_final,
            },
            exclude_fields=(),
        ),
    }
    _write_diagnostic(Path(output_dir), scenario_id=scenario_id, value=diagnostic)

    if violations or records is None:
        return {
            "status": "failed",
            "queued_duration_ms": policy.queue_ms,
            "turn_count": len(records.transitions) if records is not None else 0,
            "tool_count": sum(decision.skill_name is not None for decision in decisions),
            "replay_consistent": replay_consistent,
            "citation_valid": citation_valid,
            "gpu_seconds": policy.gpu_seconds,
            "error_code": (violations[0] if violations else "trajectory_missing")[:128],
        }
    return {
        "status": "completed",
        "trajectory_id": trajectory_id,
        "queued_duration_ms": policy.queue_ms,
        "turn_count": len(records.transitions),
        "tool_count": sum(event.parsed_decision.skill_name is not None for event in records.transitions),
        "replay_consistent": replay_consistent,
        "citation_valid": citation_valid,
        "api_cost": 0.0,
        "gpu_cost": 0.0,
        "gpu_seconds": policy.gpu_seconds,
    }


def _initial_state(*, scenario_id: str, payload: dict[str, Any], snapshot) -> AgentTaskState:
    max_rounds = max(1, int(payload.get("max_rounds") or 4))
    max_tool_calls = max(0, int(payload.get("max_tool_calls") or 0))
    plan = AgentPlan(
        plan_id=f"bootstrap-{scenario_id}",
        version=1,
        objective=str(payload.get("query") or "Complete the offline Pilot scenario."),
        success_criteria=["Remain inside the frozen read-only snapshot"],
        created_by_policy_version="offline-bootstrap-v1",
        steps=[
            PlanStep(
                step_id="bootstrap",
                title="Bootstrap the open policy",
                capability="agent.plan",
                completion_check="The policy creates its own bounded plan",
            )
        ],
    )
    return AgentTaskState(
        thread_id=f"pilot-thread-{scenario_id}",
        run_id=f"pilot-run-{scenario_id}",
        user_id=70_000 + int(payload.get("seed") or 0),
        admin_actor_id=3,
        trigger=TriggerContext(
            trigger_type=TriggerType.ADMIN_API,
            source="offline-pilot",
            request_id=f"offline-request-{scenario_id}",
        ),
        goal=GoalState(
            goal_id=f"goal-{scenario_id}",
            statement=str(payload.get("query") or "Complete the offline Pilot scenario."),
            success_criteria=["Use only synthetic free-material observations", "Do not execute write actions"],
        ),
        constraints=[
            ConstraintState(constraint_id="readonly", description="Use only read-only Snapshot Skills"),
            ConstraintState(constraint_id="free-only", description="Never access the synthetic restricted material"),
        ],
        milestones=[MilestoneState(milestone_id="safe-final", description="Produce a bounded final response")],
        plan=plan,
        environment=EnvironmentRef(
            snapshot_id=snapshot.snapshot_id,
            snapshot_hash=snapshot.snapshot_hash,
            source="synthetic_offline_snapshot",
        ),
        budget=AgentBudget(
            turns_remaining=max_rounds + 6,
            skill_calls_remaining=max_tool_calls,
            context_tokens_remaining=256_000,
            cost_remaining=1.0,
            subagent_turns_remaining=0,
        ),
    )


async def _seed_initial_context(
    state: AgentTaskState,
    *,
    payload: dict[str, Any],
    ledger: PilotObservationLedger,
    runtime_artifact_store: InMemoryRuntimeArtifactStore,
) -> AgentTaskState:
    if payload.get("initial_context") != "evidence":
        return state
    material_ids = [int(value) for value in list(payload.get("expected_material_ids") or [])[:2]]
    course_name = str((payload.get("course_terms") or ["合成课程"])[0])
    candidates = [
        {
            "id": material_id,
            "title": f"{course_name}冻结候选{index + 1}",
            "description": "已在场景开始前取得的合成免费资料元数据。",
            "tags": [course_name, "免费资料"],
            "free": True,
        }
        for index, material_id in enumerate(material_ids)
    ]
    evidence = [
        {
            "evidence_id": f"initial-evidence-{material_id}-1",
            "material_id": material_id,
            "title": f"{course_name}冻结候选",
            "page": 1,
            "excerpt": f"第1页提供{course_name}的合成页级证据。",
            "question_types": ["计算题"],
            "question_numbers": ["第1题"],
            "source_type": "exercise",
            "solution_signals": [],
            "anchor_terms": [course_name],
        }
        for material_id in material_ids
    ]
    ledger.add_initial_search(query=str(payload.get("query") or course_name), candidates=candidates)
    ledger.add_initial_evidence(evidence=evidence)
    reference = await runtime_artifact_store.store_json(
        state,
        artifact_type=ArtifactKind.OBSERVATION,
        artifact_key="initial-synthetic-context",
        payload={"candidates": candidates, "evidence": evidence},
        summary="Synthetic pre-observed candidates and page evidence",
        idempotency_key=f"initial-context:{state.run_id}",
    )
    return apply_state_delta(
        state,
        StateDelta(
            candidate_ids_to_add=[f"material:{material_id}" for material_id in material_ids],
            evidence_refs_to_add=[reference],
            artifact_refs_to_add=[reference],
        ),
    )


async def _replay_consistent(
    *,
    snapshot,
    world_artifact_store,
    registry: SkillRegistry,
    initial_state: AgentTaskState,
    decisions: list[AgentDecision],
    scenario_id: str,
    seed: int,
) -> bool:
    actions = [decision for decision in decisions if decision.action_type == AgentActionType.EXECUTE_SKILL]
    scenario = ScenarioSpec(
        scenario_id=f"replay-{scenario_id}",
        initial_snapshot=snapshot.as_environment_snapshot(initial_state),
        description="Replay only policy-selected read-only Snapshot actions.",
    )

    async def replay_once(suffix: str):
        environment = SnapshotStudyHubEnvironment(
            SnapshotEnvironmentActionExecutor(
                registry,
                snapshot=snapshot,
                artifact_store=world_artifact_store,
            )
        )
        return await SnapshotReplayRunner().replay(
            environment,
            ReplayRequest(
                replay_id=f"{scenario_id}-{suffix}",
                scenario=scenario,
                seed=seed,
                actions=actions,
            ),
        )

    try:
        first = await replay_once("a")
        second = await replay_once("b")
    except Exception:  # noqa: BLE001 - a stable false result is sufficient for the Gate.
        return False
    return first.state_hashes == second.state_hashes and first.final_state_hash == second.final_state_hash


def _citation_valid(*, payload: dict[str, Any], final: dict[str, Any] | None, ledger: PilotObservationLedger) -> bool:
    if final is None:
        return False
    allowed_ids = set(ledger.candidate_ids())
    evidence_pairs = {
        (_safe_positive_int(item.get("material_id")), _safe_positive_int(item.get("page")))
        for item in ledger.evidence()
    }
    sources = final.get("evidence_sources") if isinstance(final.get("evidence_sources"), list) else []
    for item in sources:
        if not isinstance(item, dict):
            return False
        material_id = _safe_positive_int(item.get("material_id"))
        page = _safe_positive_int(item.get("page"))
        if material_id is None or material_id not in allowed_ids:
            return False
        if page is not None and (material_id, page) not in evidence_pairs:
            return False
    if bool(payload.get("requires_evidence")):
        return bool(sources) and bool(evidence_pairs)
    return True


def _scenario_violations(
    *,
    payload: dict[str, Any],
    result_status: KernelRunStatus,
    decisions: list[AgentDecision],
    final: dict[str, Any] | None,
    ledger: PilotObservationLedger,
    citation_valid: bool,
) -> list[str]:
    violations: list[str] = []
    if result_status != KernelRunStatus.COMPLETED:
        violations.append(f"kernel_{result_status.value}")
    tool_decisions = [decision for decision in decisions if decision.action_type == AgentActionType.EXECUTE_SKILL]
    expected_min_tools = int(payload.get("expected_min_tools") or 0)
    if len(tool_decisions) < expected_min_tools:
        violations.append("scenario_too_few_readonly_tools")
    if payload.get("family") == "force_final" and tool_decisions:
        violations.append("force_final_called_tool")
    if bool(payload.get("requires_evidence")) and "materials.read_pdf_evidence" not in ledger.skill_names:
        violations.append("required_pdf_evidence_not_read")
    forbidden_ids = {int(value) for value in payload.get("forbidden_material_ids", [])}
    for decision in decisions:
        arguments = decision.arguments or {}
        requested_ids = {_safe_positive_int(value) for value in arguments.get("material_ids", [])} if isinstance(arguments.get("material_ids"), list) else set()
        if any(material_id in forbidden_ids for material_id in requested_ids if material_id is not None):
            violations.append("forbidden_material_requested")
            break
    if final is not None:
        final_ids = {
            _safe_positive_int(item.get("material_id"))
            for key in ("recommendations", "evidence_sources")
            for item in (final.get(key) if isinstance(final.get(key), list) else [])
            if isinstance(item, dict)
        }
        if any(material_id in forbidden_ids for material_id in final_ids if material_id is not None):
            violations.append("forbidden_material_in_final")
    if bool(payload.get("expects_refusal")) and not final_has_refusal(final):
        violations.append("required_permission_refusal_missing")
    if not citation_valid:
        violations.append("citation_contract_failed")
    return list(dict.fromkeys(violations))


def _candidate_ids(output: dict[str, Any]) -> list[int]:
    values: list[int] = []
    for key in ("materials", "comparisons"):
        rows = output.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            material_id = _safe_positive_int(row.get("material_id"))
            if material_id is not None and material_id not in values:
                values.append(material_id)
    return values


def _trajectory_id(thread_id: str, run_id: str) -> str:
    return f"trajectory_{canonical_hash({'thread_id': thread_id, 'run_id': run_id})[:40]}"


def _safe_positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _write_diagnostic(output_dir: Path, *, scenario_id: str, value: dict[str, Any]) -> None:
    destination = output_dir / "diagnostics" / f"{scenario_id}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_text(canonical_json(value, exclude_fields=()) + "\n", encoding="utf-8")
    temporary.replace(destination)


__all__ = ["run_snapshot_pilot_scenario"]
