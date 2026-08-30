from __future__ import annotations

import hashlib
import json
from typing import Any

from studyhub_agent.adapters.personal_memory import PersonalMemoryProvider
from studyhub_agent.guardrails.privacy import sanitize_output
from studyhub_agent.tools.registry import ToolExecutionContext, validate_arguments
from studyhub_agent.tools.schemas import TOOL_DEFINITIONS


class HermesPersonalMemoryBridge:
    """Policy-bound adapter for Hermes' upstream MemoryProvider lifecycle."""

    name = "studyhub-personal"

    def __init__(self, provider: PersonalMemoryProvider, context: ToolExecutionContext) -> None:
        self.provider = provider
        self.context = context
        self.session_id = ""

    def is_available(self) -> bool:
        return True

    def unavailable_reason(self) -> str:
        return ""

    def initialize(self, session_id: str, **kwargs: object) -> None:
        del kwargs
        self.session_id = session_id

    def system_prompt_block(self) -> str:
        return "Personal memory is isolated to the active StudyHub user and is read-only in this session."

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        del session_id
        records = self.provider.search(self.context.memory_namespace, query, limit=5)
        return "\n".join(f"- {sanitize_output(record.content)}" for record in records)

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        del query, session_id

    def recall_status(self) -> None:
        return None

    def sync_turn(
        self,
        user_content: str,
        assistant_content: str,
        *,
        session_id: str = "",
        messages: list[dict[str, object]] | None = None,
    ) -> None:
        del user_content, assistant_content, session_id, messages

    def on_session_end(self, messages: list[dict[str, object]]) -> None:
        del messages

    def on_turn_start(self, turn_number: int, message: str, **kwargs: object) -> None:
        del turn_number, message, kwargs

    def on_session_switch(self, new_session_id: str, **kwargs: object) -> None:
        del kwargs
        self.session_id = new_session_id

    def on_pre_compress(self, messages: list[dict[str, object]]) -> str:
        del messages
        return ""

    def on_delegation(self, task: str, result: str, **kwargs: object) -> None:
        del task, result, kwargs

    def get_config_schema(self) -> list[dict[str, object]]:
        return []

    def save_config(self, values: dict[str, object], hermes_home: str) -> None:
        del values, hermes_home

    def on_memory_write(
        self,
        action: str,
        target: str,
        content: str,
        metadata: dict[str, object] | None = None,
    ) -> None:
        del action, target, content, metadata

    def backup_paths(self) -> list[str]:
        return []

    def get_tool_schemas(self) -> list[dict[str, object]]:
        return [
            {
                "name": "personal_memory_search",
                "description": "Search only the active StudyHub user's isolated memory namespace.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "minLength": 1, "maxLength": 500},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            }
        ]

    def handle_tool_call(self, tool_name: str, args: dict[str, object], **kwargs: object) -> str:
        del kwargs
        if tool_name != "personal_memory_search":
            raise KeyError(tool_name)
        if tool_name not in self.context.task.allowed_tools:
            raise PermissionError(f"tool is not allowed for this task: {tool_name}")
        normalized = validate_arguments(TOOL_DEFINITIONS[tool_name], args)
        serialized = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        fingerprint = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]
        self.context.budget.authorize_tool(tool_name, fingerprint)
        records = self.provider.search(
            self.context.memory_namespace,
            str(normalized["query"]),
            limit=int(normalized["limit"]),
        )
        payload = {
            "memories": [
                {
                    "memory_id": record.memory_id,
                    "content": record.content,
                    "metadata": record.metadata,
                    "updated_at": record.updated_at,
                }
                for record in records
            ]
        }
        return json.dumps(sanitize_output(payload), ensure_ascii=False, sort_keys=True)

    def shutdown(self) -> None:
        return None


def attach_personal_memory_provider(agent: Any, provider: HermesPersonalMemoryBridge) -> frozenset[str]:
    """Attach one StudyHub provider through Hermes' native memory lifecycle.

    The caller should construct Hermes with ``skip_memory=True`` unless a
    built-in provider is deliberately required. A second external provider is
    rejected rather than silently creating two competing memory systems.
    """
    from agent.memory_manager import MemoryManager, normalize_tool_schema
    from hermes_constants import get_hermes_home

    manager = getattr(agent, "_memory_manager", None)
    if manager is None:
        manager = MemoryManager()
    external = [item.name for item in manager.providers if item.name != "builtin"]
    if external:
        raise RuntimeError(f"Hermes already has an external memory provider: {external[0]}")

    init_kwargs = {
        "hermes_home": str(get_hermes_home()),
        "platform": getattr(agent, "platform", None) or "cli",
        "agent_context": "primary",
    }
    for source, target in (
        ("_user_id", "user_id"),
        ("_user_id_alt", "user_id_alt"),
        ("_gateway_session_key", "gateway_session_key"),
    ):
        value = getattr(agent, source, None)
        if value:
            init_kwargs[target] = value
    provider.initialize(str(getattr(agent, "session_id", "")), **init_kwargs)
    manager.add_provider(provider)
    agent._memory_manager = manager
    agent._memory_provider_shutdown = False

    tools = list(getattr(agent, "tools", None) or [])
    existing = {
        item.get("function", {}).get("name")
        for item in tools
        if isinstance(item, dict)
    }
    added: set[str] = set()
    for raw_schema in provider.get_tool_schemas():
        schema = normalize_tool_schema(raw_schema)
        if schema is None:
            raise RuntimeError("StudyHub memory provider returned an invalid tool schema")
        name = str(schema["name"])
        if name in existing:
            raise RuntimeError(f"duplicate Hermes memory tool schema: {name}")
        tools.append({"type": "function", "function": schema})
        existing.add(name)
        added.add(name)

    agent.tools = tools
    agent.valid_tool_names = set(getattr(agent, "valid_tool_names", set())) | added
    return frozenset(added)
