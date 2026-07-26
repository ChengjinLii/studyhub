"""A thin adapter around the stable AgentEnvironment protocol.

No ``verl`` package, FastAPI application, model provider, or business Skill is
imported here.  A later training job can bind this adapter to the veRL version
locked for that experiment without changing the product runtime.
"""

from __future__ import annotations

from collections.abc import AsyncIterable, Iterable, Mapping
from dataclasses import dataclass

from ...trajectory.interfaces import AgentEnvironment


@dataclass(frozen=True)
class AgentLoopRollout:
    reset: object
    steps: tuple[object, ...]
    final_state_hash: str | None


class VerlAgentLoopAdapter:
    """Expose reset/step/snapshot/restore without dictating Agent behavior."""

    def __init__(self, environment: AgentEnvironment) -> None:
        self.environment = environment

    async def reset(self, scenario: object, seed: int) -> object:
        return await self.environment.reset(scenario, seed)

    async def step(self, action: object) -> object:
        return await self.environment.step(action)

    async def snapshot(self) -> object:
        return await self.environment.snapshot()

    async def restore(self, snapshot: object) -> None:
        await self.environment.restore(snapshot)

    async def rollout(
        self,
        scenario: object,
        seed: int,
        actions: Iterable[object] | AsyncIterable[object],
    ) -> AgentLoopRollout:
        reset = await self.reset(scenario, seed)
        steps: list[object] = []
        if isinstance(actions, AsyncIterable):
            async for action in actions:
                steps.append(await self.step(action))
        else:
            for action in actions:
                steps.append(await self.step(action))
        final = steps[-1] if steps else reset
        return AgentLoopRollout(reset=reset, steps=tuple(steps), final_state_hash=_state_hash(final))


def _state_hash(value: object) -> str | None:
    if isinstance(value, Mapping):
        candidate = value.get("state_after_hash") or value.get("state_hash")
    else:
        candidate = getattr(value, "state_after_hash", None) or getattr(value, "state_hash", None)
    return candidate if isinstance(candidate, str) else None
