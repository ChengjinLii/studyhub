"""Run-scoped single-writer lease shared by AgentExecution workers."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from typing import Awaitable, Callable, TypeVar

from sqlalchemy.orm import Session

from app.providers.lock import LockProvider


class RunLeaseLostError(RuntimeError):
    """Raised when durable trajectory work is attempted without its lease."""


ResultT = TypeVar("ResultT")


@dataclass(slots=True)
class RunLease:
    """Small ownership wrapper around the configured DB/Redis lock provider.

    The worker obtains this lease before a kernel is constructed and releases it
    only after its checkpoint, transition segments, and job status are handled.
    The lease name is intentionally stable: it is also the cross-process writer
    boundary for a run's immutable trajectory directory.
    """

    provider: LockProvider
    session: Session
    run_id: str
    owner_token: str
    ttl_seconds: int
    acquired: bool = False

    @property
    def lock_name(self) -> str:
        return self.name_for_run(self.run_id)

    @staticmethod
    def name_for_run(run_id: str) -> str:
        normalized = run_id.strip()
        if not normalized:
            raise ValueError("run_id must not be blank")
        return f"agent-execution:{normalized}"

    def acquire(self) -> bool:
        if self.acquired:
            return True
        self.acquired = self.provider.acquire(
            self.session,
            lock_name=self.lock_name,
            owner_token=self.owner_token,
            ttl_seconds=max(1, int(self.ttl_seconds)),
        )
        return self.acquired

    def require_held(self) -> None:
        if not self.acquired:
            raise RunLeaseLostError(f"agent execution lease is not held for run: {self.run_id}")

    def renew(self) -> bool:
        self.require_held()
        renew = getattr(self.provider, "renew", None)
        try:
            renewed = (
                renew(
                    self.session,
                    lock_name=self.lock_name,
                    owner_token=self.owner_token,
                    ttl_seconds=max(1, int(self.ttl_seconds)),
                )
                if callable(renew)
                else self.provider.acquire(
                    self.session,
                    lock_name=self.lock_name,
                    owner_token=self.owner_token,
                    ttl_seconds=max(1, int(self.ttl_seconds)),
                )
            )
        except Exception:
            self.acquired = False
            raise
        self.acquired = bool(renewed)
        return self.acquired

    async def run_with_heartbeat(
        self,
        operation: Awaitable[ResultT],
        *,
        ownership_check: Callable[[], bool] | None = None,
    ) -> ResultT:
        """Run one operation while renewing ownership and fail closed if it is lost."""

        self.require_held()
        operation_task = asyncio.ensure_future(operation)
        heartbeat_task = asyncio.create_task(self._heartbeat(ownership_check))
        try:
            done, _pending = await asyncio.wait(
                {operation_task, heartbeat_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if heartbeat_task in done:
                heartbeat_error = heartbeat_task.exception()
                operation_task.cancel()
                await asyncio.gather(operation_task, return_exceptions=True)
                if heartbeat_error is not None:
                    raise heartbeat_error
                raise RunLeaseLostError(f"agent execution lease was lost for run: {self.run_id}")
            result = await operation_task
            self._renew_and_check_ownership(ownership_check)
            return result
        finally:
            if not heartbeat_task.done():
                heartbeat_task.cancel()
                with suppress(asyncio.CancelledError):
                    await heartbeat_task

    async def _heartbeat(self, ownership_check: Callable[[], bool] | None) -> None:
        interval_seconds = max(0.1, float(self.ttl_seconds) / 3.0)
        while True:
            await asyncio.sleep(interval_seconds)
            self._renew_and_check_ownership(ownership_check)

    def _renew_and_check_ownership(self, ownership_check: Callable[[], bool] | None) -> None:
        if not self.renew():
            raise RunLeaseLostError(f"agent execution lease was lost for run: {self.run_id}")
        if ownership_check is not None and not ownership_check():
            raise RunLeaseLostError(f"agent execution job claim was lost for run: {self.run_id}")

    def release(self) -> None:
        if not self.acquired:
            return
        try:
            self.provider.release(
                self.session,
                lock_name=self.lock_name,
                owner_token=self.owner_token,
            )
        finally:
            self.acquired = False
