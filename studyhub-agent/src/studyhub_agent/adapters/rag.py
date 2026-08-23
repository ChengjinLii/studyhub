from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from studyhub_rag.retrieval import BM25Retriever
from studyhub_rag.schemas import Chunk

from studyhub_agent.guardrails.permissions import PermissionContext


@dataclass(frozen=True, slots=True)
class KnowledgeChunk:
    source_id: str
    material_id: int
    chunk_id: str
    page: int | None
    title: str
    text: str
    score: float = 0.0
    access_scope: str = "free"
    owner_id: str | None = None
    tags: tuple[str, ...] = ()
    course: str = ""

    def to_public_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["tags"] = list(self.tags)
        value.pop("access_scope", None)
        value.pop("owner_id", None)
        return value


class KnowledgeRetriever(Protocol):
    async def search(self, query: str, *, limit: int, permissions: PermissionContext) -> list[KnowledgeChunk]: ...

    async def read(self, source_id: str, *, permissions: PermissionContext) -> KnowledgeChunk | None: ...

    async def browse(
        self,
        *,
        material_id: int | None,
        source_id: str | None,
        limit: int,
        permissions: PermissionContext,
    ) -> list[KnowledgeChunk]: ...


class RagExperimentKnowledgeRetriever:
    """Adapter over the retained RAG BM25 implementation, not its experiment CLI."""

    def __init__(self, chunks: list[KnowledgeChunk]) -> None:
        self._chunks = list(chunks)
        self._by_source = {chunk.source_id: chunk for chunk in self._chunks}
        rag_chunks = [
            Chunk(
                chunk_id=chunk.source_id,
                material_id=chunk.material_id,
                title=chunk.title,
                text=chunk.text,
                tags=chunk.tags,
                course_category=chunk.course,
                page=chunk.page,
                source_kind="phase1_fixture",
            )
            for chunk in self._chunks
        ]
        self._retriever = BM25Retriever(rag_chunks)

    @classmethod
    def from_jsonl(cls, path: str | Path) -> RagExperimentKnowledgeRetriever:
        chunks: list[KnowledgeChunk] = []
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            value = json.loads(line)
            value["tags"] = tuple(value.get("tags", []))
            chunks.append(KnowledgeChunk(**value))
        return cls(chunks)

    async def search(self, query: str, *, limit: int, permissions: PermissionContext) -> list[KnowledgeChunk]:
        candidate_limit = min(len(self._chunks), max(limit * 4, limit))
        hits, _ = self._retriever.search(query, top_k=candidate_limit)
        visible: list[KnowledgeChunk] = []
        for hit in hits:
            chunk = self._by_source[hit.chunk_id]
            if permissions.can_read(chunk):
                visible.append(
                    KnowledgeChunk(**{**asdict(chunk), "tags": chunk.tags, "score": round(float(hit.score), 6)})
                )
            if len(visible) >= limit:
                break
        return visible

    async def read(self, source_id: str, *, permissions: PermissionContext) -> KnowledgeChunk | None:
        chunk = self._by_source.get(source_id)
        return chunk if chunk is not None and permissions.can_read(chunk) else None

    async def browse(
        self,
        *,
        material_id: int | None,
        source_id: str | None,
        limit: int,
        permissions: PermissionContext,
    ) -> list[KnowledgeChunk]:
        anchor = self._by_source.get(source_id or "")
        target_material = material_id or (anchor.material_id if anchor else None)
        if target_material is None:
            return []
        return [
            chunk for chunk in self._chunks if chunk.material_id == target_material and permissions.can_read(chunk)
        ][:limit]
