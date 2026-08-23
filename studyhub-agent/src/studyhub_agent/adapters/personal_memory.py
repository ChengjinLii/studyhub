from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from time import time
from typing import Protocol


@dataclass(frozen=True, slots=True)
class PersonalMemory:
    memory_id: str
    namespace: str
    content: str
    metadata: dict[str, object] = field(default_factory=dict)
    updated_at: float = field(default_factory=time)


class PersonalMemoryProvider(Protocol):
    def search(self, namespace: str, query: str, *, limit: int) -> list[PersonalMemory]: ...

    def add(self, namespace: str, content: str, metadata: dict[str, object] | None = None) -> PersonalMemory: ...

    def update(self, namespace: str, memory_id: str, content: str) -> PersonalMemory | None: ...

    def delete(self, namespace: str, memory_id: str) -> bool: ...

    def reset_namespace(self, namespace: str) -> int: ...


class InMemoryPersonalMemoryProvider:
    def __init__(self) -> None:
        self._records: dict[str, dict[str, PersonalMemory]] = {}
        self._lock = threading.RLock()

    def search(self, namespace: str, query: str, *, limit: int) -> list[PersonalMemory]:
        terms = {term.casefold() for term in query.split() if term.strip()}
        with self._lock:
            records = list(self._records.get(namespace, {}).values())
        scored = [(sum(term in record.content.casefold() for term in terms), record) for record in records]
        return [record for score, record in sorted(scored, key=lambda row: (-row[0], -row[1].updated_at)) if score][
            :limit
        ]

    def add(self, namespace: str, content: str, metadata: dict[str, object] | None = None) -> PersonalMemory:
        record = PersonalMemory(
            memory_id=f"memory:{uuid.uuid4().hex}",
            namespace=namespace,
            content=content.strip(),
            metadata=dict(metadata or {}),
        )
        if not record.content:
            raise ValueError("memory content must not be empty")
        with self._lock:
            self._records.setdefault(namespace, {})[record.memory_id] = record
        return record

    def update(self, namespace: str, memory_id: str, content: str) -> PersonalMemory | None:
        with self._lock:
            current = self._records.get(namespace, {}).get(memory_id)
            if current is None:
                return None
            updated = PersonalMemory(
                memory_id=current.memory_id,
                namespace=namespace,
                content=content.strip(),
                metadata=current.metadata,
            )
            self._records[namespace][memory_id] = updated
            return updated

    def delete(self, namespace: str, memory_id: str) -> bool:
        with self._lock:
            return self._records.get(namespace, {}).pop(memory_id, None) is not None

    def reset_namespace(self, namespace: str) -> int:
        with self._lock:
            return len(self._records.pop(namespace, {}))


class HermesPersonalMemoryBridge:
    """Duck-typed adapter for Hermes' upstream MemoryProvider lifecycle."""

    name = "studyhub-personal"

    def __init__(self, provider: PersonalMemoryProvider, namespace: str) -> None:
        self.provider = provider
        self.namespace = namespace
        self.session_id = ""

    def is_available(self) -> bool:
        return True

    def initialize(self, session_id: str, **kwargs: object) -> None:
        self.session_id = session_id

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        records = self.provider.search(self.namespace, query, limit=5)
        return "\n".join(f"- {record.content}" for record in records)

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
        query = str(args.get("query", "")).strip()
        limit = int(args.get("limit", 5))
        records = self.provider.search(self.namespace, query, limit=limit)
        return json.dumps({"memories": [asdict(record) for record in records]}, ensure_ascii=False)

    def shutdown(self) -> None:
        return None
