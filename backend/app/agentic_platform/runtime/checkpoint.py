from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

import aiosqlite
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import Field

from app.agentic_platform.domain import DomainModel
from app.agentic_platform.domain.hashing import canonical_json


class RuntimeCheckpointSnapshot(DomainModel):
    """A compact mirror used for Redis recovery and operational inspection."""

    schema_version: str = "1.0"
    graph_thread_id: str = Field(min_length=1, max_length=256)
    run_id: str = Field(min_length=1, max_length=128)
    state_hash: str = Field(min_length=1, max_length=128)
    graph_state: dict[str, Any]
    next_nodes: list[str] = Field(default_factory=list)


class RedisLike(Protocol):
    def set(self, name: str, value: str, ex: int | None = None) -> object:
        ...

    def get(self, name: str) -> bytes | str | None:
        ...


class RedisCheckpointAdapter:
    """Redis mirror adapter; LangGraph remains responsible for graph scheduling."""

    def __init__(self, client: RedisLike, *, key_prefix: str = "studyhub:agentic:checkpoint", ttl_seconds: int | None = None) -> None:
        if not key_prefix.strip():
            raise ValueError("key_prefix must not be blank")
        self.client = client
        self.key_prefix = key_prefix.rstrip(":")
        self.ttl_seconds = ttl_seconds

    def save(self, snapshot: RuntimeCheckpointSnapshot) -> str:
        key = self._key(snapshot.graph_thread_id)
        self.client.set(key, canonical_json(snapshot, exclude_fields=()), ex=self.ttl_seconds)
        return f"redis://{self.key_prefix}/{snapshot.graph_thread_id}"

    def load(self, graph_thread_id: str) -> RuntimeCheckpointSnapshot | None:
        value = self.client.get(self._key(graph_thread_id))
        if value is None:
            return None
        rendered = value.decode("utf-8") if isinstance(value, bytes) else value
        return RuntimeCheckpointSnapshot.model_validate_json(rendered)

    def _key(self, graph_thread_id: str) -> str:
        if not graph_thread_id.strip():
            raise ValueError("graph_thread_id must not be blank")
        return f"{self.key_prefix}:{graph_thread_id}"


class InMemoryCheckpointHandle:
    kind = "in_memory"

    def __init__(self) -> None:
        self.checkpointer = InMemorySaver()

    def checkpoint_ref(self, graph_thread_id: str) -> str:
        return f"langgraph-memory://{graph_thread_id}"

    async def close(self) -> None:
        return None


class SQLiteCheckpointHandle:
    kind = "sqlite"

    def __init__(self, connection: aiosqlite.Connection, checkpointer: AsyncSqliteSaver) -> None:
        self._connection = connection
        self.checkpointer = checkpointer

    @classmethod
    async def open(cls, path: str | Path) -> "SQLiteCheckpointHandle":
        connection = await aiosqlite.connect(str(path))
        checkpointer = AsyncSqliteSaver(connection)
        await checkpointer.setup()
        return cls(connection, checkpointer)

    def checkpoint_ref(self, graph_thread_id: str) -> str:
        return f"langgraph-sqlite://{graph_thread_id}"

    async def close(self) -> None:
        await self._connection.close()
