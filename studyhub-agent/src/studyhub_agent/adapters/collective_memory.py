from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from studyhub_agent.guardrails.privacy import sanitize_output


@dataclass(frozen=True, slots=True)
class CollectiveMemory:
    memory_id: str
    course: str
    scenario: str
    pattern: str
    support_users: int
    support_episodes: int
    confidence: float


class CollectiveMemoryReader(Protocol):
    def search(self, query: str, *, course: str = "", limit: int = 5) -> list[CollectiveMemory]: ...


class FixtureCollectiveMemoryReader:
    def __init__(self, records: list[CollectiveMemory]) -> None:
        self._records = records

    @classmethod
    def from_json(cls, path: str | Path) -> FixtureCollectiveMemoryReader:
        values = json.loads(Path(path).read_text(encoding="utf-8"))
        forbidden = {"username", "email", "raw_user_id", "user_id", "chat_transcript"}
        if any(forbidden.intersection(value) for value in values):
            raise ValueError("collective memory fixture contains user-level data")
        return cls([CollectiveMemory(**value) for value in values])

    def search(self, query: str, *, course: str = "", limit: int = 5) -> list[CollectiveMemory]:
        terms = {term.casefold() for term in query.split() if term.strip()}
        scored: list[tuple[int, CollectiveMemory]] = []
        for record in self._records:
            if course and course.casefold() not in record.course.casefold():
                continue
            searchable = f"{record.course} {record.scenario} {record.pattern}".casefold()
            score = sum(term in searchable for term in terms)
            if score:
                scored.append((score, record))
        return [record for _, record in sorted(scored, key=lambda row: (-row[0], -row[1].confidence))[:limit]]

    def public_results(self, query: str, *, course: str = "", limit: int = 5) -> list[dict[str, object]]:
        return [sanitize_output(asdict(record)) for record in self.search(query, course=course, limit=limit)]
