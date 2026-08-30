from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
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
