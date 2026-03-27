from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.finance import WorkerLockRecord
from app.repos.finance_repo import FinanceRepository


class LockProvider(Protocol):
    provider_name: str

    def acquire(self, session: Session, *, lock_name: str, owner_token: str, ttl_seconds: int) -> bool: ...

    def release(self, session: Session, *, lock_name: str, owner_token: str) -> None: ...

    def probe(self, *, deep: bool = False) -> dict[str, Any]: ...


class DbRowLockProvider:
    provider_name = "db_row"

    def __init__(self, finance_repo: FinanceRepository) -> None:
        self.finance_repo = finance_repo

    def acquire(self, session: Session, *, lock_name: str, owner_token: str, ttl_seconds: int) -> bool:
        now = datetime.now(UTC)
        lock = self.finance_repo.get_worker_lock(session, lock_name)
        if (
            lock is not None
            and lock.expires_at is not None
            and self._normalize_dt(lock.expires_at) > now
            and lock.owner_token != owner_token
        ):
            session.rollback()
            return False
        if lock is None:
            lock = WorkerLockRecord(name=lock_name)
        lock.owner_token = owner_token
        lock.acquired_at = now
        lock.expires_at = now + timedelta(seconds=max(1, ttl_seconds))
        self.finance_repo.save_worker_lock(session, lock)
        session.commit()
        return True

    def release(self, session: Session, *, lock_name: str, owner_token: str) -> None:
        lock = self.finance_repo.get_worker_lock(session, lock_name)
        if lock is None:
            session.rollback()
            return
        if lock.owner_token not in {None, owner_token}:
            session.rollback()
            return
        lock.owner_token = None
        lock.expires_at = datetime.now(UTC)
        self.finance_repo.save_worker_lock(session, lock)
        session.commit()

    def probe(self, *, deep: bool = False) -> dict[str, Any]:
        del deep
        return {
            "status": "ok",
            "provider": self.provider_name,
            "mode": "database-row-lock",
        }

    def _normalize_dt(self, value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class RedisLockProvider:
    provider_name = "redis"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def acquire(self, session: Session, *, lock_name: str, owner_token: str, ttl_seconds: int) -> bool:
        del session
        client = self._client()
        key = self._key(lock_name)
        acquired = bool(client.set(key, owner_token, nx=True, ex=max(1, ttl_seconds)))
        if acquired:
            return True
        current = client.get(key)
        if current and current.decode("utf-8") == owner_token:
            client.expire(key, max(1, ttl_seconds))
            return True
        return False

    def release(self, session: Session, *, lock_name: str, owner_token: str) -> None:
        del session
        client = self._client()
        key = self._key(lock_name)
        with client.pipeline() as pipe:
            while True:
                try:
                    pipe.watch(key)
                    current = pipe.get(key)
                    if current and current.decode("utf-8") != owner_token:
                        pipe.unwatch()
                        return
                    pipe.multi()
                    pipe.delete(key)
                    pipe.execute()
                    return
                except Exception:
                    pipe.reset()
                    return

    def probe(self, *, deep: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": "ok",
            "provider": self.provider_name,
            "namespace": self.settings.redis_namespace,
        }
        if deep:
            payload["ping"] = bool(self._client().ping())
        return payload

    def _client(self):
        try:
            import redis  # type: ignore[import-not-found]
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("Redis lock provider 依赖缺失，请安装 redis。") from exc
        return redis.Redis.from_url(
            self.settings.redis_url,
            socket_timeout=self.settings.redis_socket_timeout_seconds,
            socket_connect_timeout=self.settings.redis_connect_timeout_seconds,
            decode_responses=False,
        )

    def _key(self, lock_name: str) -> str:
        namespace = self.settings.redis_namespace.strip(":")
        prefix = self.settings.redis_lock_key_prefix.strip(":")
        return f"{namespace}:{prefix}:{lock_name}"
