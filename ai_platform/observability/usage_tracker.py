from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class UsageEvent:
    provider: str
    model: str
    operation: str
    status: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    input_count: int = 0
    output_count: int = 0
    error_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "provider": self.provider,
            "model": self.model,
            "operation": self.operation,
            "status": self.status,
            "promptTokens": self.prompt_tokens,
            "completionTokens": self.completion_tokens,
            "totalTokens": self.total_tokens,
            "inputCount": self.input_count,
            "outputCount": self.output_count,
            "errorType": self.error_type,
        }


class JsonlUsageTracker:
    """Append-only local usage tracker that never stores prompts or secrets."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def record(self, event: UsageEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")

    def summarize(self) -> dict[str, Any]:
        events = self.read_events()
        return {
            "eventCount": len(events),
            "totalTokens": sum(int(event.get("totalTokens") or 0) for event in events),
            "promptTokens": sum(int(event.get("promptTokens") or 0) for event in events),
            "completionTokens": sum(int(event.get("completionTokens") or 0) for event in events),
            "errors": sum(1 for event in events if event.get("status") != "success"),
            "operations": sorted({str(event.get("operation")) for event in events}),
        }

    def read_events(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        events: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))
        return events


def get_env_usage_tracker(prefix: str = "STUDYHUB_USAGE") -> JsonlUsageTracker | None:
    path = os.getenv(f"{prefix}_LOG_PATH")
    if not path:
        return None
    return JsonlUsageTracker(Path(path))
