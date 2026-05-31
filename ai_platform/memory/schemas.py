from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MemoryCandidate:
    scope: str
    key: str
    value: str
    confidence: float
    source: str

    def to_dict(self) -> dict[str, object]:
        return {
            "scope": self.scope,
            "key": self.key,
            "value": self.value,
            "confidence": round(self.confidence, 4),
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "MemoryCandidate":
        return cls(
            scope=str(value["scope"]),
            key=str(value["key"]),
            value=str(value["value"]),
            confidence=float(value.get("confidence") or 0.0),
            source=str(value.get("source") or "unknown"),
        )
