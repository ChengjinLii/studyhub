from __future__ import annotations

import json

from studyhub_agent.tools.registry import ToolExecutionContext, ToolRegistry
from studyhub_agent.tools.schemas import TOOL_DEFINITIONS


class HermesToolBridge:
    """Register StudyHub capabilities through Hermes' public tool registry."""

    def __init__(self, registry: ToolRegistry, context: ToolExecutionContext) -> None:
        self._studyhub_registry = registry
        self._context = context
        self._installed: list[str] = []
        self._replaced: dict[str, object] = {}

    def install(self) -> None:
        from tools.registry import registry as hermes_registry

        for name in self._context.task.allowed_tools:
            definition = TOOL_DEFINITIONS[name]
            existing = hermes_registry.get_entry(name)
            if existing is not None:
                self._replaced[name] = existing

            async def handler(arguments, _name=name, **_kwargs):
                result = await self._studyhub_registry.dispatch(_name, arguments, self._context)
                return json.dumps(result, ensure_ascii=False, sort_keys=True)

            hermes_registry.register(
                name=name,
                toolset="studyhub",
                schema={
                    "name": name,
                    "description": definition.description,
                    "parameters": definition.parameters,
                },
                handler=handler,
                is_async=True,
                description=definition.description,
                max_result_size_chars=20_000,
                override=existing is not None,
            )
            self._installed.append(name)

    def uninstall(self) -> None:
        from tools.registry import registry as hermes_registry

        for name in reversed(self._installed):
            hermes_registry.deregister(name)
            existing = self._replaced.get(name)
            if existing is not None:
                hermes_registry.register(
                    name=existing.name,
                    toolset=existing.toolset,
                    schema=existing.schema,
                    handler=existing.handler,
                    check_fn=existing.check_fn,
                    requires_env=existing.requires_env,
                    is_async=existing.is_async,
                    description=existing.description,
                    emoji=existing.emoji,
                    max_result_size_chars=existing.max_result_size_chars,
                    dynamic_schema_overrides=existing.dynamic_schema_overrides,
                )
        self._installed.clear()
        self._replaced.clear()

    def __enter__(self) -> HermesToolBridge:
        self.install()
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.uninstall()
