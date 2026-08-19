from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from sqlalchemy.orm import Session

from app.agentic_platform.deepresearch import (
    DeepResearchGraph,
    ModelResearchPolicy,
    ResearchCapabilityFlags,
    ResearchDomainRouter,
    ResearchRuntimeMetadata,
    StudyHubResearchEnvironment,
)
from app.agentic_platform.deepresearch.state import ResearchTaskPacket
from app.agentic_platform.deepresearch.web_adapter import build_web_research_adapter
from app.agentic_platform.persistence.durable_artifact_store import (
    DurableArtifactStore,
    DurableResearchArtifactStore,
    DurableResearchTraceStore,
    LocalFilesystemArtifactBlobStore,
    OssArtifactBlobStore,
)
from app.agentic_platform.persistence.durable_transition_sink import DurableTransitionSink
from app.agentic_platform.policy.context_builder import ContextBuilder
from app.agentic_platform.domain.hashing import canonical_hash
from app.agentic_platform.policy.model_policy import ModelPolicy
from app.agentic_platform.policy.provider_factory import build_agent_model_provider
from app.agentic_platform.runtime.kernel import AgentKernel
from app.agentic_platform.runtime.checkpoint import SQLiteCheckpointHandle
from app.agentic_platform.runtime.nodes import RegistrySkillActionExecutor, RuntimeMetadata
from app.agentic_platform.runtime.persistence import SqlAlchemyRuntimePersistence
from app.agentic_platform.skills.context import SkillExecutionContext, SkillExecutionMode
from app.agentic_platform.skills.executor import LiveSkillExecutor
from app.agentic_platform.skills.registry import SkillRegistry
from app.agentic_platform.subagents.deepresearch import (
    DeepResearchDelegateExecutor,
    DeepResearchSearchAgent,
    DeepResearchSubAgentResult,
)
from app.core.config import Settings
from app.models.agentic_runtime import AgentRunRecord
from app.services.read_support import ROLE_ADMIN

from .errors import AgentExecutionConfigurationError


BuildResultT = TypeVar("BuildResultT")
AgentKernelBuilder = Callable[[AgentRunRecord, dict[str, object]], AgentKernel | Awaitable[AgentKernel]]
DeepResearchAgentBuilder = Callable[
    [AgentRunRecord, ResearchTaskPacket],
    DeepResearchSearchAgent | Awaitable[DeepResearchSearchAgent],
]
DeepResearchResultPersister = Callable[
    [AgentRunRecord, DeepResearchSubAgentResult, str],
    int | Awaitable[int],
]
SessionFactory = Callable[[], Session]


@dataclass(frozen=True, slots=True)
class DurableRuntimeDependencies:
    """Live dependencies passed by API wiring without importing API globals."""

    session_factory: SessionFactory
    skill_registry: SkillRegistry
    material_repository: object
    materials_service: object
    pdf_evidence_service: object
    storage_provider: object | None = None


class AgentRuntimeFactory:
    """Dependency-injected construction boundary for the execution worker.

    The factory deliberately has no scripted policy or fixed action path. R2
    wires a real model provider here; tests can provide bounded fixture
    builders without changing worker/job semantics.
    """

    def __init__(
        self,
        *,
        agent_kernel_builder: AgentKernelBuilder | None = None,
        deep_research_agent_builder: DeepResearchAgentBuilder | None = None,
        deep_research_result_persister: DeepResearchResultPersister | None = None,
    ) -> None:
        self._agent_kernel_builder = agent_kernel_builder
        self._deep_research_agent_builder = deep_research_agent_builder
        self._deep_research_result_persister = deep_research_result_persister

    async def build_agent_kernel(
        self,
        *,
        run: AgentRunRecord,
        dispatch_payload: dict[str, object],
    ) -> AgentKernel:
        if self._agent_kernel_builder is None:
            raise AgentExecutionConfigurationError()
        built = self._agent_kernel_builder(run, dispatch_payload)
        return await _resolve(built)

    async def build_deep_research_agent(
        self,
        *,
        run: AgentRunRecord,
        research_task: ResearchTaskPacket,
    ) -> DeepResearchSearchAgent:
        if self._deep_research_agent_builder is None:
            raise AgentExecutionConfigurationError()
        built = self._deep_research_agent_builder(run, research_task)
        return await _resolve(built)

    async def persist_deep_research_result(
        self,
        *,
        run: AgentRunRecord,
        result: DeepResearchSubAgentResult,
        idempotency_key: str,
    ) -> int | None:
        if self._deep_research_result_persister is None:
            return None
        return await _resolve(self._deep_research_result_persister(run, result, idempotency_key))


async def _resolve(value: BuildResultT | Awaitable[BuildResultT]) -> BuildResultT:
    if isinstance(value, Awaitable):
        return await value
    return value


def build_durable_agent_runtime_factory(
    settings: Settings,
    *,
    dependencies: DurableRuntimeDependencies,
) -> AgentRuntimeFactory:
    """Build the opt-in production runtime without constraining policy paths.

    The wiring supplies replaceable providers, skills, and research adapters;
    it only fixes durability/ACL boundaries.  It does not prescribe any action
    sequence, capability choice, or re-plan count for the agent.
    """

    if not settings.agentic_durable_storage_enabled or settings.agentic_checkpointer != "sqlite":
        raise AgentExecutionConfigurationError("agent_execution_durable_storage_not_configured")
    model_provider = build_agent_model_provider(settings)
    artifact_store = DurableArtifactStore(
        dependencies.session_factory,
        blob_store=_build_blob_store(settings, dependencies=dependencies),
    )
    transition_sink = DurableTransitionSink(settings.resolved_agentic_transition_root_dir)
    all_scopes = frozenset(
        scope
        for skill in dependencies.skill_registry.list()
        for scope in skill.spec.permission_scopes
    )
    catalog_hash = _skill_catalog_hash(dependencies.skill_registry)

    async def build_kernel(run: AgentRunRecord, dispatch_payload: dict[str, object]) -> AgentKernel:
        del dispatch_payload
        checkpoint = await _open_durable_checkpointer(settings)
        live_session = dependencies.session_factory()
        try:
            metadata = _runtime_metadata(run, settings, skill_catalog_hash=catalog_hash)
            skill_executor = LiveSkillExecutor(dependencies.skill_registry)
            research_environment = _build_research_environment(
                run=run,
                settings=settings,
                dependencies=dependencies,
                session=live_session,
            )

            def context_factory(state, decision) -> SkillExecutionContext:
                del decision
                if state.run_id != run.id or state.thread_id != run.thread_id or state.admin_actor_id != run.admin_actor_id:
                    raise ValueError("agent runtime state does not belong to its durable run")
                return SkillExecutionContext(
                    admin_actor_id=run.admin_actor_id,
                    role_mask=ROLE_ADMIN,
                    permission_scopes=all_scopes,
                    current_user_id=run.admin_actor_id,
                    current_user_role_mask=ROLE_ADMIN,
                    session=live_session,
                    material_repo=dependencies.material_repository,  # type: ignore[arg-type]
                    materials_service=dependencies.materials_service,  # type: ignore[arg-type]
                    pdf_evidence_service=dependencies.pdf_evidence_service,  # type: ignore[arg-type]
                    research_environment=research_environment,
                    research_capability_flags=ResearchCapabilityFlags(
                        web_enabled=settings.deep_research_web_enabled,
                        scholar_enabled=settings.deep_research_scholar_enabled,
                    ),
                    mode=SkillExecutionMode.LIVE,
                )

            skill_action_executor = RegistrySkillActionExecutor(
                registry=dependencies.skill_registry,
                executor=skill_executor,
                context_factory=context_factory,
                artifact_store=artifact_store,
            )
            research_agent = _build_research_agent(
                run=run,
                settings=settings,
                dependencies=dependencies,
                artifact_store=artifact_store,
                transition_sink=transition_sink,
                model_provider=model_provider,
                session=live_session,
                checkpointer=checkpoint.checkpointer,
                skill_catalog_hash=catalog_hash,
                environment=research_environment,
            )
            return AgentKernel(
                policy=ModelPolicy(model_provider, raw_output_store=artifact_store),
                context_builder=ContextBuilder(token_budget=settings.agentic_max_context_tokens),
                skill_registry=dependencies.skill_registry,
                skill_action_executor=skill_action_executor,
                checkpointer=checkpoint,
                subagent_executor=DeepResearchDelegateExecutor(research_agent),
                artifact_store=artifact_store,
                transition_sink=transition_sink,
                model_turn_sink=transition_sink,
                persistence=SqlAlchemyRuntimePersistence(
                    dependencies.session_factory,
                    metadata=metadata,
                ),
                metadata=metadata,
                close_callbacks=[live_session.close],
            )
        except Exception:
            live_session.close()
            await checkpoint.close()
            raise

    async def build_research(run: AgentRunRecord, research_task: ResearchTaskPacket) -> DeepResearchSearchAgent:
        checkpoint = await _open_durable_checkpointer(settings)
        live_session = dependencies.session_factory()
        try:
            agent = _build_research_agent(
                run=run,
                settings=settings,
                dependencies=dependencies,
                artifact_store=artifact_store,
                transition_sink=transition_sink,
                model_provider=model_provider,
                session=live_session,
                checkpointer=checkpoint.checkpointer,
                skill_catalog_hash=catalog_hash,
            )
            agent.add_close_callbacks([live_session.close, checkpoint.close])
            if research_task.admin_actor_id != run.admin_actor_id:
                raise ValueError("research task owner does not match run owner")
            return agent
        except Exception:
            live_session.close()
            await checkpoint.close()
            raise

    def persist_research_result(run: AgentRunRecord, result: DeepResearchSubAgentResult, job_id: str) -> int:
        packet = result.research_packet.model_dump(mode="json")
        report = result.research_report.model_dump(mode="json")
        artifact_store.store_json_for_owner(
            thread_id=run.thread_id,
            run_id=run.id,
            admin_actor_id=run.admin_actor_id,
            artifact_type="research_packet",
            artifact_key=f"deep-research:{run.id}:packet",
            payload=packet,
            summary="Typed DeepResearch packet",
            idempotency_key=f"deep-research-packet:{job_id}",
        )
        artifact_store.store_json_for_owner(
            thread_id=run.thread_id,
            run_id=run.id,
            admin_actor_id=run.admin_actor_id,
            artifact_type="research_report",
            artifact_key=f"deep-research:{run.id}:report",
            payload=report,
            summary="Typed DeepResearch report",
            idempotency_key=f"deep-research-report:{job_id}",
        )
        return 2

    return AgentRuntimeFactory(
        agent_kernel_builder=build_kernel,
        deep_research_agent_builder=build_research,
        deep_research_result_persister=persist_research_result,
    )


def _build_research_agent(
    *,
    run: AgentRunRecord,
    settings: Settings,
    dependencies: DurableRuntimeDependencies,
    artifact_store: DurableArtifactStore,
    transition_sink: DurableTransitionSink,
    model_provider,
    session: Session,
    checkpointer: Any,
    skill_catalog_hash: str,
    environment: StudyHubResearchEnvironment | None = None,
) -> DeepResearchSearchAgent:
    research_artifacts = DurableResearchArtifactStore(
        artifact_store,
        thread_id=run.thread_id,
        run_id=run.id,
        admin_actor_id=run.admin_actor_id,
    )
    environment = environment or _build_research_environment(
        run=run,
        settings=settings,
        dependencies=dependencies,
        session=session,
    )
    graph = DeepResearchGraph(
        policy=ModelResearchPolicy(
            model_provider,
            token_budget=settings.agentic_max_context_tokens,
            raw_output_store=research_artifacts,
        ),
        router=ResearchDomainRouter(
            environment,
            flags=ResearchCapabilityFlags(
                web_enabled=settings.deep_research_web_enabled,
                scholar_enabled=settings.deep_research_scholar_enabled,
            ),
        ),
        checkpointer=checkpointer,
        trace_store=DurableResearchTraceStore(research_artifacts),
        artifact_store=research_artifacts,
        transition_sink=transition_sink.research_child_sink(thread_id=run.thread_id, run_id=run.id),
        metadata=_research_runtime_metadata(run, settings, skill_catalog_hash=skill_catalog_hash),
    )
    return DeepResearchSearchAgent(graph)


def _build_research_environment(
    *,
    run: AgentRunRecord,
    settings: Settings,
    dependencies: DurableRuntimeDependencies,
    session: Session,
) -> StudyHubResearchEnvironment:
    return StudyHubResearchEnvironment(
        session=session,
        material_repo=dependencies.material_repository,  # type: ignore[arg-type]
        materials_service=dependencies.materials_service,  # type: ignore[arg-type]
        pdf_evidence_service=dependencies.pdf_evidence_service,  # type: ignore[arg-type]
        admin_actor_id=run.admin_actor_id,
        role_mask=ROLE_ADMIN,
        web_adapter=build_web_research_adapter(settings),
    )


def _build_blob_store(settings: Settings, *, dependencies: DurableRuntimeDependencies):
    if settings.agentic_artifact_storage_provider == "local_fs":
        return LocalFilesystemArtifactBlobStore(settings.resolved_agentic_blob_root_dir)
    provider = dependencies.storage_provider
    if provider is None or getattr(provider, "provider_name", None) != "oss":
        raise AgentExecutionConfigurationError()
    return OssArtifactBlobStore(
        provider=provider,
        staging_root=settings.resolved_agentic_artifact_root_dir / ".oss-staging",
    )


async def _open_durable_checkpointer(settings: Settings) -> SQLiteCheckpointHandle:
    if settings.agentic_checkpointer != "sqlite":
        raise AgentExecutionConfigurationError()
    path = settings.resolved_agentic_checkpoint_path
    path.parent.mkdir(parents=True, exist_ok=True)
    return await SQLiteCheckpointHandle.open(path)


def _runtime_metadata(
    run: AgentRunRecord,
    settings: Settings,
    *,
    skill_catalog_hash: str,
) -> RuntimeMetadata:
    return RuntimeMetadata(
        runtime_version=run.runtime_version,
        policy_version=run.policy_version,
        model_id=settings.agentic_model_id or "configured-agentic-model",
        model_revision=settings.agentic_model_revision,
        skill_catalog_hash=skill_catalog_hash,
        retriever_version=settings.agentic_retriever_version or "unconfigured-retriever",
    )


def _research_runtime_metadata(
    run: AgentRunRecord,
    settings: Settings,
    *,
    skill_catalog_hash: str,
) -> ResearchRuntimeMetadata:
    return ResearchRuntimeMetadata(
        policy_version=run.policy_version,
        skill_catalog_hash=skill_catalog_hash,
        retriever_version=settings.agentic_retriever_version or "unconfigured-retriever",
        environment_snapshot_id=run.environment_snapshot_id,
        environment_snapshot_hash=_environment_snapshot_hash(run),
    )


def _skill_catalog_hash(registry: SkillRegistry) -> str:
    """Hash every registered typed capability and version in execution order."""

    return canonical_hash([skill.spec.model_dump(mode="json") for skill in registry.list()])


def _environment_snapshot_hash(run: AgentRunRecord) -> str:
    """Match the immutable envelope hash constructed by the execution worker."""

    return canonical_hash(
        {
            "snapshot_id": run.environment_snapshot_id,
            "run_id": run.id,
            "thread_id": run.thread_id,
        }
    )
