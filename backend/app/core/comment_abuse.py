from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from hashlib import sha256
import re
import secrets
from threading import RLock
from time import monotonic
from typing import Any

from app.core.config import Settings
from app.core.exceptions import BizException
from app.core.observability import get_runtime_metrics
from app.core.rate_limit import rate_limit_key_allowed
from app.core.redis_client import create_redis_client, redis_namespace


COMMENT_ACTIONS = {"create", "update", "delete", "like", "unlike", "report"}
_LOCAL_DUPLICATE_ENTRY_LIMIT = 4096


@dataclass(frozen=True, slots=True)
class CommentContentReservation:
    key: str
    token: str
    backend: str


class CommentDuplicateGuard:
    _RELEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""

    def __init__(self) -> None:
        self._entries: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._lock = RLock()
        self._redis_client: Any | None = None

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
        self._redis_client = None

    def reserve(
        self,
        settings: Settings,
        *,
        user_id: int,
        material_id: int,
        parent_id: int | None,
        content: str,
    ) -> CommentContentReservation | None:
        ttl_seconds = max(0, int(settings.rate_limit_comment_duplicate_seconds or 0))
        if ttl_seconds == 0:
            return None
        key = self._key(
            settings,
            user_id=user_id,
            material_id=material_id,
            parent_id=parent_id,
            content=content,
        )
        token = secrets.token_urlsafe(18)
        if self._uses_redis(settings):
            try:
                client = self._client(settings)
                if client.set(key, token, nx=True, ex=ttl_seconds):
                    return CommentContentReservation(key=key, token=token, backend="redis")
                _reject_duplicate_comment()
            except BizException:
                raise
            except Exception:
                pass
        return self._reserve_local(key, token, ttl_seconds)

    def release(self, reservation: CommentContentReservation | None) -> None:
        if reservation is None:
            return
        if reservation.backend == "redis" and self._redis_client is not None:
            try:
                self._redis_client.eval(self._RELEASE_SCRIPT, 1, reservation.key, reservation.token)
                return
            except Exception:
                return
        with self._lock:
            current = self._entries.get(reservation.key)
            if current is not None and current[1] == reservation.token:
                self._entries.pop(reservation.key, None)

    def _reserve_local(self, key: str, token: str, ttl_seconds: int) -> CommentContentReservation:
        now = monotonic()
        with self._lock:
            self._prune_local(now)
            if key in self._entries:
                _reject_duplicate_comment()
            self._entries[key] = (now + ttl_seconds, token)
            self._entries.move_to_end(key)
            while len(self._entries) > _LOCAL_DUPLICATE_ENTRY_LIMIT:
                self._entries.popitem(last=False)
        return CommentContentReservation(key=key, token=token, backend="local")

    def _prune_local(self, now: float) -> None:
        expired = [key for key, (expires_at, _) in self._entries.items() if expires_at <= now]
        for key in expired:
            self._entries.pop(key, None)

    def _client(self, settings: Settings):
        if self._redis_client is None:
            self._redis_client = create_redis_client(settings, decode_responses=True)
        return self._redis_client

    @staticmethod
    def _uses_redis(settings: Settings) -> bool:
        backend = (settings.rate_limit_backend or "auto").strip().lower()
        return bool(settings.redis_url and backend in {"auto", "redis"})

    @staticmethod
    def _key(
        settings: Settings,
        *,
        user_id: int,
        material_id: int,
        parent_id: int | None,
        content: str,
    ) -> str:
        normalized = re.sub(r"\s+", " ", content.strip()).casefold()
        digest = sha256(normalized.encode("utf-8")).hexdigest()
        parent_key = int(parent_id or 0)
        return (
            f"{redis_namespace(settings)}:comment-deduplicate:"
            f"user:{int(user_id)}:material:{int(material_id)}:parent:{parent_key}:{digest}"
        )


_COMMENT_DUPLICATE_GUARD = CommentDuplicateGuard()


def get_comment_duplicate_guard() -> CommentDuplicateGuard:
    return _COMMENT_DUPLICATE_GUARD


def clear_comment_abuse_state() -> None:
    _COMMENT_DUPLICATE_GUARD.clear()


def enforce_comment_user_rate_limit(settings: Settings, *, user_id: int, action: str) -> None:
    if not settings.comments_write_enabled:
        raise BizException(
            "COMMENTS_READ_ONLY",
            "评论区暂时处于只读状态，请稍后再试",
            status_code=503,
        )
    if not settings.rate_limit_enabled:
        return
    normalized_action = action.strip().lower()
    if normalized_action not in COMMENT_ACTIONS:
        raise ValueError(f"unsupported comment action: {action}")
    rules: list[tuple[str, int, int]] = []
    if normalized_action == "create":
        rules.extend(
            (
                ("comment-create-user-minute", settings.rate_limit_comment_create_user_minute, 60),
                ("comment-create-user-hour", settings.rate_limit_comment_create_user_hour, 3600),
            )
        )
    else:
        rules.append(
            (f"comment-{normalized_action}-user-minute", settings.rate_limit_comment_action_user_minute, 60)
        )
    if normalized_action == "report":
        rules.append(("comment-report-user-hour", settings.rate_limit_comment_report_user_hour, 3600))
    for name, limit, window_seconds in rules:
        key = f"{name}:user:{int(user_id)}"
        if rate_limit_key_allowed(settings, key, limit=limit, window_seconds=window_seconds):
            continue
        get_runtime_metrics().record_security_event(event="comment_rate_limit", reason=name)
        raise BizException(
            "COMMENT_RATE_LIMITED",
            "评论操作过于频繁，请稍后再试",
            status_code=429,
        )


def reserve_comment_content(
    settings: Settings,
    *,
    user_id: int,
    material_id: int,
    parent_id: int | None,
    content: str,
) -> CommentContentReservation | None:
    return _COMMENT_DUPLICATE_GUARD.reserve(
        settings,
        user_id=user_id,
        material_id=material_id,
        parent_id=parent_id,
        content=content,
    )


def release_comment_content(reservation: CommentContentReservation | None) -> None:
    _COMMENT_DUPLICATE_GUARD.release(reservation)


def _reject_duplicate_comment() -> None:
    get_runtime_metrics().record_security_event(event="comment_duplicate", reason="same_user_material_content")
    raise BizException(
        "COMMENT_DUPLICATE",
        "相同评论正在处理或刚刚已经提交，请勿重复发布",
        status_code=409,
    )
