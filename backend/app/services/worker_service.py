from __future__ import annotations

from datetime import UTC, datetime, timedelta
import uuid
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.providers.lock import LockProvider
from app.services.payout_service import PayoutService
from app.services.requests_service import RequestsService


class WorkerService:
    """独立 worker 的任务入口，不把调度塞进 Web app startup。"""

    def __init__(
        self,
        settings: Settings,
        payout_service: PayoutService,
        requests_service: RequestsService,
        lock_provider: LockProvider,
    ) -> None:
        self.settings = settings
        self.payout_service = payout_service
        self.requests_service = requests_service
        self.lock_provider = lock_provider

    def run_settlement_job(self, session: Session, *, owner_token: str | None = None) -> dict[str, Any]:
        return self._run_locked(
            session,
            lock_name=self.settings.settlement_lock_name,
            lock_timeout_seconds=self.settings.settlement_lock_timeout_seconds,
            owner_token=owner_token,
            task=lambda: {"generated": self.payout_service.generate_pending_settlements(session)},
        )

    def run_request_refund_job(self, session: Session, *, owner_token: str | None = None) -> dict[str, Any]:
        return self._run_locked(
            session,
            lock_name=self.settings.request_refund_lock_name,
            lock_timeout_seconds=self.settings.request_refund_lock_timeout_seconds,
            owner_token=owner_token,
            task=lambda: self.requests_service.run_scheduled_refunds(session),
        )

    def run_payout_transfer_job(self, session: Session, *, owner_token: str | None = None) -> dict[str, Any]:
        return self._run_locked(
            session,
            lock_name=self.settings.payout_transfer_lock_name,
            lock_timeout_seconds=self.settings.payout_transfer_lock_timeout_seconds,
            owner_token=owner_token,
            task=lambda: {"processed": self.payout_service.refresh_pending_transfers(session)},
        )

    def run_named_job(self, session: Session, job_name: str, *, owner_token: str | None = None) -> dict[str, Any]:
        normalized = (job_name or "all").strip().lower()
        if normalized == "settlement":
            return self.run_settlement_job(session, owner_token=owner_token)
        if normalized in {"request-refund", "refund"}:
            return self.run_request_refund_job(session, owner_token=owner_token)
        if normalized in {"payout-transfer", "transfer"}:
            return self.run_payout_transfer_job(session, owner_token=owner_token)
        if normalized == "all":
            return {
                "settlement": self.run_settlement_job(session, owner_token=owner_token),
                "requestRefund": self.run_request_refund_job(session, owner_token=owner_token),
                "payoutTransfer": self.run_payout_transfer_job(session, owner_token=owner_token),
            }
        raise ValueError(f"Unsupported job: {job_name}")

    def try_acquire_lock(self, session: Session, *, lock_name: str, owner_token: str | None = None, ttl_seconds: int | None = None) -> bool:
        token = owner_token or uuid.uuid4().hex
        ttl = max(1, ttl_seconds or self.settings.worker_lock_ttl_seconds)
        return self.lock_provider.acquire(session, lock_name=lock_name, owner_token=token, ttl_seconds=ttl)

    def release_lock(self, session: Session, *, lock_name: str, owner_token: str | None = None) -> None:
        self.lock_provider.release(session, lock_name=lock_name, owner_token=owner_token or "")

    def _run_locked(
        self,
        session: Session,
        *,
        lock_name: str,
        lock_timeout_seconds: int,
        owner_token: str | None,
        task: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        token = owner_token or uuid.uuid4().hex
        acquired = self.try_acquire_lock(
            session,
            lock_name=lock_name,
            owner_token=token,
            ttl_seconds=max(lock_timeout_seconds, self.settings.worker_lock_ttl_seconds),
        )
        if not acquired:
            return {"lockName": lock_name, "acquired": False}
        try:
            result = task()
            return {"lockName": lock_name, "acquired": True, **result}
        finally:
            self.release_lock(session, lock_name=lock_name, owner_token=token)
