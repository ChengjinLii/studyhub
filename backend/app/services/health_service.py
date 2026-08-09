from __future__ import annotations

import logging
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.providers.kyc import KycProvider
from app.providers.lock import LockProvider
from app.providers.mail import MailProvider
from app.providers.payment import PaymentGatewayProvider
from app.providers.storage import StorageProvider
from app.providers.transfer import PayoutTransferProvider
from app.repos.system_repo import SystemRepository


logger = logging.getLogger(__name__)


class HealthService:
    def __init__(
        self,
        settings: Settings,
        system_repo: SystemRepository,
        mail_provider: MailProvider,
        storage_provider: StorageProvider,
        payment_provider: PaymentGatewayProvider,
        transfer_provider: PayoutTransferProvider,
        kyc_provider: KycProvider,
        lock_provider: LockProvider,
    ) -> None:
        self.settings = settings
        self.system_repo = system_repo
        self.mail_provider = mail_provider
        self.storage_provider = storage_provider
        self.payment_provider = payment_provider
        self.transfer_provider = transfer_provider
        self.kyc_provider = kyc_provider
        self.lock_provider = lock_provider

    def build_public_payload(self) -> dict[str, object]:
        return {"status": "ok"}

    def build_readiness_payload(self, session: Session, *, deep: bool = False) -> dict[str, object]:
        checks = {
            "database": self._probe(lambda: self._probe_database(session)),
            "mail": self._probe(lambda: self.mail_provider.probe(deep=deep)),
            "storage": self._probe(
                lambda: self.storage_provider.probe(root=self.settings.resolved_material_asset_dir, deep=deep)
            ),
            "payment": self._probe(lambda: self.payment_provider.probe(deep=deep)),
            "transfer": self._probe(lambda: self.transfer_provider.probe(deep=deep)),
            "kyc": self._probe(lambda: self.kyc_provider.probe(deep=deep)),
            "lock": self._probe(lambda: self.lock_provider.probe(deep=deep)),
        }
        overall_status = "ok" if all(item["status"] == "ok" for item in checks.values()) else "degraded"
        return {
            "status": overall_status,
            "service": self.settings.app_name,
            "environment": self.settings.environment,
            "deep": deep,
            "checks": checks,
            "build": {
                "gitSha": self.settings.resolved_build_git_sha,
                "source": "fastapi",
            },
        }

    def _probe_database(self, session: Session) -> dict[str, Any]:
        self.system_repo.ping(session)
        return {
            "status": "ok",
            "provider": "sqlalchemy",
            "dialect": "sqlite" if self.settings.database_is_sqlite else "mysql",
        }

    def _probe(self, callback: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        try:
            result = callback()
            result.setdefault("status", "ok")
            return result
        except Exception:  # noqa: BLE001
            logger.exception("Readiness dependency probe failed", extra={"event": "readiness_probe_failed"})
            return {
                "status": "error",
                "message": "Dependency probe failed",
            }
