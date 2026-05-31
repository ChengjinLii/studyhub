from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class QueryEntities:
    course: str | None = None
    school: str | None = None
    college: str | None = None
    major: str | None = None
    grade: str | None = None
    exam_time: str | None = None
    level: str | None = None
    material_types: tuple[str, ...] = ()
    knowledge_points: tuple[str, ...] = ()
    budget: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "course": self.course,
            "school": self.school,
            "college": self.college,
            "major": self.major,
            "grade": self.grade,
            "examTime": self.exam_time,
            "level": self.level,
            "materialTypes": list(self.material_types),
            "knowledgePoints": list(self.knowledge_points),
            "budget": self.budget,
        }


@dataclass(frozen=True)
class SearchTask:
    type: str
    query: str
    top_k: int = 5

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "query": self.query, "topK": self.top_k}


@dataclass(frozen=True)
class QueryUnderstanding:
    raw_query: str
    intent: str
    query_rewrite: str
    entities: QueryEntities
    search_tasks: tuple[SearchTask, ...]
    suggestions: tuple[str, ...] = ()
    fallback_used: bool = False
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rawQuery": self.raw_query,
            "intent": self.intent,
            "queryRewrite": self.query_rewrite,
            "entities": self.entities.to_dict(),
            "searchTasks": [task.to_dict() for task in self.search_tasks],
            "suggestions": list(self.suggestions),
            "fallbackUsed": self.fallback_used,
            "warnings": list(self.warnings),
        }
