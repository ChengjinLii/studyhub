from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Chunk:
    chunk_id: str
    material_id: int
    title: str
    text: str
    tags: tuple[str, ...] = ()
    course_category: str = ""
    school: str = ""
    college: str = ""
    major: str = ""
    grade_type: str = ""
    grade_value: str = ""
    page: int | None = None
    source_kind: str = "metadata"
    source_path: str = ""

    @property
    def retrieval_text(self) -> str:
        header = " ".join(part for part in (self.title, " ".join(self.tags), self.major, self.course_category) if part)
        return f"{header}\n{self.text}".strip()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["tags"] = list(self.tags)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Chunk:
        value = dict(payload)
        value["tags"] = tuple(value.get("tags") or ())
        return cls(**value)


@dataclass(frozen=True, slots=True)
class QueryCase:
    query_id: str
    query: str
    query_type: str
    relevance: dict[int, int]
    notes: str = ""

    @property
    def answerable(self) -> bool:
        return bool(self.relevance)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> QueryCase:
        relevance = {int(key): int(value) for key, value in (payload.get("relevance") or {}).items()}
        return cls(
            query_id=str(payload["query_id"]),
            query=str(payload["query"]),
            query_type=str(payload.get("query_type") or "unspecified"),
            relevance=relevance,
            notes=str(payload.get("notes") or ""),
        )


@dataclass(frozen=True, slots=True)
class SearchHit:
    chunk_id: str
    material_id: int
    score: float
    rank: int
    title: str = ""
    text: str = ""

    def with_rank(self, rank: int) -> SearchHit:
        return SearchHit(
            chunk_id=self.chunk_id,
            material_id=self.material_id,
            score=self.score,
            rank=rank,
            title=self.title,
            text=self.text,
        )
