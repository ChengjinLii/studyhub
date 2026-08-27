from __future__ import annotations

import json

from studyhub_agent.integrations.hermes_registry import HermesRegistryOverlay
from studyhub_agent.tools.registry import ToolExecutionContext, ToolRegistry
from studyhub_agent.tools.schemas import TOOL_DEFINITIONS


class HermesToolBridge:
    """Register StudyHub capabilities through Hermes' public tool registry."""

    def __init__(self, registry: ToolRegistry, context: ToolExecutionContext) -> None:
        self._studyhub_registry = registry
        self._context = context
        self._overlay: HermesRegistryOverlay | None = None

    def install(self) -> None:
        from tools.registry import registry as hermes_registry

        overlay = HermesRegistryOverlay(hermes_registry)
        for name in self._context.task.allowed_tools:
            definition = TOOL_DEFINITIONS[name]

            async def handler(arguments, _name=name, **_kwargs):
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

    def __enter__(self) -> HermesToolBridge:
        self.install()
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.uninstall()
