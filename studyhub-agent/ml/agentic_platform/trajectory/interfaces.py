"""Training-side interfaces intentionally independent of FastAPI and veRL."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class AgentEnvironment(Protocol):
    """Structural contract mirrored by the product's simulation environment."""

    async def reset(self, scenario: object, seed: int) -> object:
        ...

    async def step(self, action: object) -> object:
        ...

    async def snapshot(self) -> object:
        ...

    async def restore(self, snapshot: object) -> None:
        ...
