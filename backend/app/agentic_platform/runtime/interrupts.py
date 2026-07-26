from __future__ import annotations

import asyncio
import re
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from app.agentic_platform.domain import DomainModel
from app.agentic_platform.domain.hashing import canonical_hash, canonical_json


_SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(?:[a-z0-9_-]*?(?:api[_-]?key|access[_-]?token|token|secret|password|authorization|cookie|credential))\b\s*[:=]\s*[^\s,;]+"
)


class RunNotWaitingError(RuntimeError):
    pass


class DuplicateResumeError(RuntimeError):
    pass


class SafeResumePayload(DomainModel):
    summary: str
    payload_hash: str


class ResumeCoordinator:
    """Serializes resume/cancel handoffs without limiting later agent choices."""

    def __init__(self) -> None:
        self._guard = asyncio.Lock()
        self._locks: dict[str, asyncio.Lock] = {}

    @asynccontextmanager
    async def hold(self, run_id: str) -> AsyncIterator[None]:
        async with self._guard:
            lock = self._locks.setdefault(run_id, asyncio.Lock())
        async with lock:
            yield


class CancellationRegistry:
    def __init__(self) -> None:
        self._reasons: dict[str, str] = {}

    def request(self, run_id: str, *, reason: str) -> None:
        self._reasons.setdefault(run_id, reason)

    def requested_reason(self, run_id: str) -> str | None:
        return self._reasons.get(run_id)

    def clear(self, run_id: str) -> None:
        self._reasons.pop(run_id, None)


def safe_resume_payload(value: Any, *, max_length: int = 1_000) -> SafeResumePayload:
    rendered = canonical_json(value, exclude_fields=()) if isinstance(value, (dict, list, tuple)) else str(value or "")
    summary = " ".join(rendered.split()).strip()
    summary = _SECRET_ASSIGNMENT_PATTERN.sub("[redacted]", summary)
    summary = summary[:max_length] or "[empty response]"
    return SafeResumePayload(summary=summary, payload_hash=canonical_hash(value))
