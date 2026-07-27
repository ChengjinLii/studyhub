"""Run-scoped single-writer lease shared by AgentExecution workers."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.providers.lock import LockProvider


class RunLeaseLostError(RuntimeError):
    """Raised when durable trajectory work is attempted without its lease."""


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
