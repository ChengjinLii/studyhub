from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import dataclass
from typing import Any

from studyhub_agent.adapters.personal_memory import PersonalMemoryProvider
from studyhub_agent.integrations.hermes_memory import HermesPersonalMemoryBridge, attach_personal_memory_provider
from studyhub_agent.integrations.hermes_registry import HermesRegistryOverlay
from studyhub_agent.tools.registry import ToolExecutionContext, ToolRegistry
from studyhub_agent.tools.schemas import (
    HERMES_MEMORY_TOOL_NAMES,
    HERMES_NATIVE_TOOL_NAMES,
    STUDYHUB_DOMAIN_TOOL_NAMES,
)


@dataclass(frozen=True, slots=True)
class HermesToolPlan:
    allowed_tools: tuple[str, ...]
    studyhub_tools: tuple[str, ...]
    native_tools: tuple[str, ...]
    memory_tools: tuple[str, ...]
    enabled_toolsets: tuple[str, ...]


def build_hermes_tool_plan(
    registry: ToolRegistry,
    context: ToolExecutionContext,
    *,
    personal_memory: PersonalMemoryProvider | None,
) -> HermesToolPlan:
    """Resolve one task to a minimal, single-owner Hermes tool surface."""
    allowed = tuple(context.task.allowed_tools)
    if "web_fetch" in allowed:
        raise ValueError("web_fetch is replay-only; production Hermes tasks must use native web_extract")

    known = registry.names | HERMES_NATIVE_TOOL_NAMES | HERMES_MEMORY_TOOL_NAMES
    unknown = sorted(set(allowed) - known)
    if unknown:
        raise ValueError(f"unsupported production tools: {unknown}")

    studyhub = tuple(name for name in allowed if name in registry.names)
    native = tuple(name for name in allowed if name in HERMES_NATIVE_TOOL_NAMES)
    memory = tuple(name for name in allowed if name in HERMES_MEMORY_TOOL_NAMES)
    if memory and personal_memory is None:
        raise ValueError("personal_memory_search requires a Hermes personal-memory provider")

    toolsets: list[str] = []
    if studyhub:
        toolsets.append("studyhub")
    if native:
        toolsets.append("web")
    # An explicit unknown/empty toolset prevents Hermes from expanding to all
    # built-ins before the memory provider schema is attached and projected.
    if not toolsets:
        toolsets.append("studyhub")
    return HermesToolPlan(
        allowed_tools=allowed,
        studyhub_tools=studyhub,
        native_tools=native,
        memory_tools=memory,
        enabled_toolsets=tuple(toolsets),
    )


class HermesDomainToolBridge:
    """Expose only StudyHub-owned domain capabilities through Hermes."""

    def __init__(self, registry: ToolRegistry, context: ToolExecutionContext) -> None:
        unexpected = sorted(registry.names - STUDYHUB_DOMAIN_TOOL_NAMES)
        if unexpected:
            raise ValueError(f"non-domain tools cannot enter the production bridge: {unexpected}")
        self._studyhub_registry = registry
        self._context = context
        self._overlay: HermesRegistryOverlay | None = None

    def install(self) -> None:
        from tools.registry import registry as hermes_registry

        overlay = HermesRegistryOverlay(hermes_registry)
        for name in self._context.task.allowed_tools:
            if name not in self._studyhub_registry.names:
                continue
            definition = self._studyhub_registry.definition(name)

            async def handler(arguments: dict[str, Any], _name: str = name, **_kwargs: Any) -> str:
                result = await self._studyhub_registry.dispatch(_name, arguments, self._context)
                return json.dumps(result, ensure_ascii=False, sort_keys=True)

            try:
                overlay.install(
                    name=name,
                    toolset="studyhub",
                    schema={
                        "name": name,
                        "description": definition.description,
                        "parameters": definition.parameters,
                    },
                    handler=handler,
                    max_result_size_chars=20_000,
                )
            except BaseException:
                overlay.restore()
                raise
        self._overlay = overlay

    def uninstall(self) -> None:
        if self._overlay is not None:
            self._overlay.restore()
            self._overlay = None


class HermesNativeToolPolicy:
    """Apply StudyHub allowlist/budget policy while delegating to Hermes tools."""

    def __init__(self, context: ToolExecutionContext, tool_names: tuple[str, ...]) -> None:
        self._context = context
        self._tool_names = tool_names
        self._overlay: HermesRegistryOverlay | None = None

    def install(self) -> None:
        from tools.registry import registry as hermes_registry

        overlay = HermesRegistryOverlay(hermes_registry)
        for name in self._tool_names:
            entry = hermes_registry.get_entry(name)
            if entry is None or entry.toolset != "web":
                overlay.restore()
                raise RuntimeError(f"required Hermes native web tool is unavailable: {name}")

            async def guarded_handler(
                arguments: dict[str, Any],
                _entry: Any = entry,
                _name: str = name,
                **kwargs: Any,
            ) -> Any:
                serialized = json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                fingerprint = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]
                self._context.budget.authorize_tool(_name, fingerprint)
                result = _entry.handler(arguments, **kwargs)
                if inspect.isawaitable(result):
                    return await result
                return result

            try:
                overlay.install(
                    name=name,
                    toolset=entry.toolset,
                    schema=dict(entry.schema),
                    handler=guarded_handler,
                    check_fn=entry.check_fn,
                    requires_env=list(entry.requires_env),
                    emoji=entry.emoji,
                    max_result_size_chars=entry.max_result_size_chars or 100_000,
                    dynamic_schema_overrides=entry.dynamic_schema_overrides,
                )
            except BaseException:
                overlay.restore()
                raise
        self._overlay = overlay

    def uninstall(self) -> None:
        if self._overlay is not None:
            self._overlay.restore()
            self._overlay = None


def constrain_hermes_tool_surface(agent: Any, allowed_tools: tuple[str, ...]) -> None:
    """Fail closed unless Hermes exposes exactly the task-scoped tool names."""
    allowed = set(allowed_tools)
    projected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for schema in list(getattr(agent, "tools", None) or []):
        name = schema.get("function", {}).get("name") if isinstance(schema, dict) else None
        if name not in allowed:
            continue
        if name in seen:
            raise RuntimeError(f"duplicate tool schema on Hermes surface: {name}")
        projected.append(schema)
        seen.add(name)
    missing = sorted(allowed - seen)
    if missing:
        raise RuntimeError(f"Hermes did not expose required task tools: {missing}")
    agent.tools = projected
    agent.valid_tool_names = seen


class HermesRuntimeTools:
    """Compose Hermes-native and StudyHub-domain capabilities without duplicates."""

    def __init__(
        self,
        registry: ToolRegistry,
        context: ToolExecutionContext,
        *,
        personal_memory: PersonalMemoryProvider | None = None,
    ) -> None:
        self._context = context
        self._personal_memory = personal_memory
        self.plan = build_hermes_tool_plan(registry, context, personal_memory=personal_memory)
        self._domain = HermesDomainToolBridge(registry, context)
        self._native = HermesNativeToolPolicy(context, self.plan.native_tools)
        self._installed = False
        self._bound_agent_id: int | None = None

    @property
    def enabled_toolsets(self) -> list[str]:
        return list(self.plan.enabled_toolsets)

    def install(self) -> None:
        if self._installed:
            raise RuntimeError("Hermes runtime tools are already installed")
        self._domain.install()
        try:
            self._native.install()
        except BaseException:
            self._domain.uninstall()
            raise
        self._installed = True

    def bind_agent(self, agent: Any) -> None:
        if not self._installed:
            raise RuntimeError("install Hermes runtime tools before constructing the agent")
        if self._bound_agent_id is not None:
            raise RuntimeError("Hermes runtime tools are already bound to an agent")
        if self.plan.memory_tools:
            if self._personal_memory is None:  # pragma: no cover - enforced by the plan
                raise RuntimeError("personal memory provider is missing")
            bridge = HermesPersonalMemoryBridge(self._personal_memory, self._context)
            added = attach_personal_memory_provider(agent, bridge)
            if added != set(self.plan.memory_tools):
                raise RuntimeError(
                    f"unexpected Hermes memory surface: expected={self.plan.memory_tools}, actual={sorted(added)}"
                )
        constrain_hermes_tool_surface(agent, self.plan.allowed_tools)
        self._bound_agent_id = id(agent)

    def uninstall(self) -> None:
        if not self._installed:
            return
        try:
            self._native.uninstall()
        finally:
            self._domain.uninstall()
            self._installed = False

    def __enter__(self) -> HermesRuntimeTools:
        self.install()
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.uninstall()
