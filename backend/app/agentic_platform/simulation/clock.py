"""Deterministic clock primitives carried by a frozen world snapshot."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pydantic import Field, field_validator

from app.agentic_platform.domain import DomainModel


class ClockState(DomainModel):
    """A replayable logical clock; it never reads the host wall clock."""

    schema_version: str = "1.0"
    started_at: datetime
    tick: int = Field(default=0, ge=0)
    tick_seconds: int = Field(default=1, ge=0, le=86_400)

    @field_validator("started_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("clock timestamps must include a timezone")
        return value.astimezone(UTC)

    @property
    def now(self) -> datetime:
        return self.started_at + timedelta(seconds=self.tick * self.tick_seconds)

    def advanced(self, steps: int = 1) -> "ClockState":
        if steps < 0:
            raise ValueError("clock steps must not be negative")
        return self.model_copy(update={"tick": self.tick + steps})


class SnapshotClock:
    """Mutable wrapper used inside one rollout while preserving its seed state."""

    def __init__(self, state: ClockState) -> None:
        self._state = state.model_copy(deep=True)

    @property
    def state(self) -> ClockState:
        return self._state.model_copy(deep=True)

    @property
    def now(self) -> datetime:
        return self._state.now

    def advance(self, steps: int = 1) -> datetime:
        self._state = self._state.advanced(steps)
        return self._state.now
