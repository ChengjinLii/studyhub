from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_platform.memory.schemas import MemoryCandidate


@dataclass(frozen=True)
class StoredMemory:
    id: str
    candidate: MemoryCandidate
    created_at: str
    updated_at: str
    event_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "candidate": self.candidate.to_dict(),
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "eventCount": self.event_count,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "StoredMemory":
        return cls(
            id=str(value["id"]),
            candidate=MemoryCandidate.from_dict(dict(value["candidate"])),
            created_at=str(value["createdAt"]),
            updated_at=str(value["updatedAt"]),
            event_count=int(value.get("eventCount") or 1),
        )


class JsonHermesMemoryStore:
    """Small JSON memory store for isolated v9 demos.

    This is deliberately not a production user table. It gives the AI platform a
    testable read/update/delete contract before any real user memory integration.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def upsert_candidates(self, candidates: list[MemoryCandidate]) -> list[StoredMemory]:
        candidates = self._filter_enabled_candidates(candidates)
        existing = {memory.id: memory for memory in self.list_memories()}
        now = _now()
        updated: list[StoredMemory] = []
        for candidate in candidates:
            memory_id = _memory_id(candidate)
            current = existing.get(memory_id)
            if current:
                stored = StoredMemory(
                    id=memory_id,
                    candidate=candidate,
                    created_at=current.created_at,
                    updated_at=now,
                    event_count=current.event_count + 1,
                )
            else:
                stored = StoredMemory(
                    id=memory_id,
                    candidate=candidate,
                    created_at=now,
                    updated_at=now,
                    event_count=1,
                )
            existing[memory_id] = stored
            updated.append(stored)
        self._write(list(existing.values()))
        return updated

    def user_memory_enabled(self) -> bool:
        return bool(self._read_payload().get("preferences", {}).get("userMemoryEnabled", True))

    def set_user_memory_enabled(self, enabled: bool, *, clear_existing: bool = False) -> None:
        memories = self.list_memories()
        if not enabled and clear_existing:
            memories = [memory for memory in memories if memory.candidate.scope != "user"]
        self._write(memories, user_memory_enabled=enabled)

    def list_memories(self, *, scope: str | None = None) -> list[StoredMemory]:
        raw = self._read_payload()
        items = raw.get("memories") or []
        if not isinstance(items, list):
            raise ValueError("memory store memories must be a list")
        memories = [StoredMemory.from_dict(dict(item)) for item in items if isinstance(item, dict)]
        if scope:
            return [memory for memory in memories if memory.candidate.scope == scope]
        return memories

    def delete_memory(self, memory_id: str) -> bool:
        memories = self.list_memories()
        kept = [memory for memory in memories if memory.id != memory_id]
        if len(kept) == len(memories):
            return False
        self._write(kept)
        return True

    def clear_scope(self, scope: str) -> int:
        memories = self.list_memories()
        kept = [memory for memory in memories if memory.candidate.scope != scope]
        deleted = len(memories) - len(kept)
        self._write(kept)
        return deleted

    def _filter_enabled_candidates(self, candidates: list[MemoryCandidate]) -> list[MemoryCandidate]:
        if self.user_memory_enabled():
            return candidates
        return [candidate for candidate in candidates if candidate.scope != "user"]

    def _read_payload(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "preferences": {"userMemoryEnabled": True}, "memories": []}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("memory store root must be an object")
        preferences = raw.get("preferences")
        if not isinstance(preferences, dict):
            raw["preferences"] = {"userMemoryEnabled": True}
        elif "userMemoryEnabled" not in preferences:
            preferences["userMemoryEnabled"] = True
        return raw

    def _write(self, memories: list[StoredMemory], *, user_memory_enabled: bool | None = None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        enabled = self.user_memory_enabled() if user_memory_enabled is None else user_memory_enabled
        payload = {
            "version": 1,
            "updatedAt": _now(),
            "preferences": {"userMemoryEnabled": enabled},
            "memories": [memory.to_dict() for memory in sorted(memories, key=lambda item: item.id)],
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _memory_id(candidate: MemoryCandidate) -> str:
    return f"{candidate.scope}:{candidate.key}:{candidate.value}".lower()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
