from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import secrets
from threading import RLock
from time import time
from typing import Any, NoReturn, Sequence

from fastapi import HTTPException, status

from app.core.config import Settings
from app.core.redis_client import create_redis_client, redis_namespace
from app.schemas.upload_authorization import (
    MaterialUploadAuthorizationResponsePayload,
    UploadFileDescriptorPayload,
)


@dataclass(slots=True)
class _LocalUploadTicket:
    user_id: int
    submission_id: str
    descriptor_digest: str
    expires_at: float
    used: bool = False


@dataclass(slots=True)
class _LocalReservation:
    descriptor_digest: str
    total_bytes: int
    active_ticket_key: str | None
    expires_at: float


class UploadAuthorizationService:
    _ISSUE_SCRIPT = """
local now = tonumber(ARGV[1])
local expires_at = tonumber(ARGV[2])
local ticket_ttl = tonumber(ARGV[3])
local daily_ttl = tonumber(ARGV[4])
local submission_limit = tonumber(ARGV[5])
local bytes_limit = tonumber(ARGV[6])
local concurrent_limit = tonumber(ARGV[7])
local total_bytes = tonumber(ARGV[8])
local file_count = tonumber(ARGV[9])
local user_id = ARGV[10]
local submission_id = ARGV[11]
local descriptor_digest = ARGV[12]

redis.call('ZREMRANGEBYSCORE', KEYS[3], '-inf', now)
local reservation_exists = redis.call('EXISTS', KEYS[2]) == 1
if reservation_exists then
  if redis.call('HGET', KEYS[2], 'descriptor_digest') ~= descriptor_digest then
    return {-4, 0, 0}
  end
  local old_ticket = redis.call('HGET', KEYS[2], 'active_ticket_key')
  if old_ticket and old_ticket ~= '' then
    redis.call('DEL', old_ticket)
    redis.call('ZREM', KEYS[3], old_ticket)
  end
end

if redis.call('ZCARD', KEYS[3]) >= concurrent_limit then
  return {-3, 0, 0}
end

local submission_count = tonumber(redis.call('HGET', KEYS[1], 'submission_count') or '0')
local byte_count = tonumber(redis.call('HGET', KEYS[1], 'byte_count') or '0')
if not reservation_exists then
  if submission_count + 1 > submission_limit then
    return {-1, 0, 0}
  end
  if byte_count + total_bytes > bytes_limit then
    return {-2, 0, 0}
  end
  submission_count = redis.call('HINCRBY', KEYS[1], 'submission_count', 1)
  byte_count = redis.call('HINCRBY', KEYS[1], 'byte_count', total_bytes)
  redis.call('EXPIRE', KEYS[1], daily_ttl)
end

redis.call('HSET', KEYS[4],
  'user_id', user_id,
  'submission_id', submission_id,
  'descriptor_digest', descriptor_digest,
  'total_bytes', total_bytes,
  'file_count', file_count,
  'used', 0,
  'issued_at', now)
redis.call('EXPIRE', KEYS[4], ticket_ttl)
redis.call('ZADD', KEYS[3], expires_at, KEYS[4])
redis.call('EXPIRE', KEYS[3], ticket_ttl + 60)
redis.call('HSET', KEYS[2],
  'descriptor_digest', descriptor_digest,
  'total_bytes', total_bytes,
  'active_ticket_key', KEYS[4])
redis.call('EXPIRE', KEYS[2], daily_ttl)
return {1, submission_limit - submission_count, bytes_limit - byte_count}
"""

    _CONSUME_SCRIPT = """
if redis.call('EXISTS', KEYS[1]) == 0 then
  return {-1}
end
if redis.call('HGET', KEYS[1], 'used') == '1' then
  return {-2}
end
if redis.call('HGET', KEYS[1], 'user_id') ~= ARGV[1]
  or redis.call('HGET', KEYS[1], 'submission_id') ~= ARGV[2]
  or redis.call('HGET', KEYS[1], 'descriptor_digest') ~= ARGV[3] then
  return {-3}
end
redis.call('HSET', KEYS[1], 'used', 1, 'used_at', ARGV[4])
redis.call('HDEL', KEYS[1], 'user_id', 'submission_id', 'descriptor_digest', 'total_bytes', 'file_count')
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[5]))
redis.call('ZREM', KEYS[2], KEYS[1])
if redis.call('HGET', KEYS[3], 'active_ticket_key') == KEYS[1] then
  redis.call('HDEL', KEYS[3], 'active_ticket_key')
end
return {1}
"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._redis_client: Any | None = None
        self._local_tickets: dict[str, _LocalUploadTicket] = {}
        self._local_reservations: dict[str, _LocalReservation] = {}
        self._local_quotas: dict[str, tuple[int, int, float]] = {}
        self._lock = RLock()

    def authorize(
        self,
        *,
        user_id: int,
        submission_id: str,
        files: Sequence[UploadFileDescriptorPayload],
    ) -> MaterialUploadAuthorizationResponsePayload:
        normalized = self.validate_descriptors(files)
        descriptor_digest = self.descriptor_digest(normalized)
        total_bytes = sum(item.sizeBytes for item in normalized)
        token = secrets.token_urlsafe(32)
        token_key = self._ticket_key(self._token_digest(token))
        ttl = max(60, int(self.settings.upload_authorization_ttl_seconds))
        now = time()
        if self._backend() == "redis":
            try:
                result = self._client().eval(
                    self._ISSUE_SCRIPT,
                    4,
                    self._quota_key(user_id),
                    self._reservation_key(user_id, submission_id),
                    self._active_key(user_id),
                    token_key,
                    now,
                    now + ttl,
                    ttl,
                    172800,
                    int(self.settings.upload_daily_submission_limit),
                    int(self.settings.upload_daily_bytes_limit),
                    int(self.settings.upload_max_concurrent_authorizations),
                    total_bytes,
                    len(normalized),
                    user_id,
                    submission_id,
                    descriptor_digest,
                )
            except Exception as exc:  # noqa: BLE001
                self._raise_unavailable(exc)
            return self._to_response(token, ttl, result)
        return self._authorize_local(
            token=token,
            token_key=token_key,
            user_id=user_id,
            submission_id=submission_id,
            descriptor_digest=descriptor_digest,
            total_bytes=total_bytes,
            ttl=ttl,
        )

    def consume(
        self,
        *,
        token: str,
        user_id: int,
        submission_id: str,
        files: Sequence[UploadFileDescriptorPayload],
    ) -> None:
        normalized_token = (token or "").strip()
        if not normalized_token:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="缺少上传授权，请重新提交")
        normalized = self.validate_descriptors(files)
        digest = self.descriptor_digest(normalized)
        ticket_key = self._ticket_key(self._token_digest(normalized_token))
        reservation_key = self._reservation_key(user_id, submission_id)
        if self._backend() == "redis":
            try:
                result = self._client().eval(
                    self._CONSUME_SCRIPT,
                    3,
                    ticket_key,
                    self._active_key(user_id),
                    reservation_key,
                    str(user_id),
                    submission_id,
                    digest,
                    time(),
                    max(30, int(self.settings.upload_authorization_consumed_marker_ttl_seconds)),
                )
            except Exception as exc:  # noqa: BLE001
                self._raise_unavailable(exc)
            self._raise_consume_error(int(result[0]))
            return
        self._consume_local(ticket_key, user_id=user_id, submission_id=submission_id, descriptor_digest=digest)

    def validate_descriptors(
        self,
        files: Sequence[UploadFileDescriptorPayload],
    ) -> list[UploadFileDescriptorPayload]:
        normalized = list(files)
        if len(normalized) > int(self.settings.upload_max_file_count):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="本次上传文件数量过多")
        role_counts = {"MATERIAL": 0, "PREVIEW": 0, "CUSTOM_PREVIEW": 0}
        for item in normalized:
            role_counts[item.role] += 1
            suffix = Path(item.name.replace("\\", "/")).suffix.lower()
            if item.role == "MATERIAL":
                if suffix not in self.settings.resolved_upload_allowed_material_extensions:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"不支持上传 {suffix or '无扩展名'} 文件")
                if item.sizeBytes > int(self.settings.material_file_max_size_bytes):
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="资料文件大小不能超过 50MB")
            else:
                if suffix not in self.settings.resolved_safe_image_extensions:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="预览图格式不支持")
                if item.contentType.lower() not in self.settings.resolved_safe_image_mime_types:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="预览图类型不支持")
                if item.sizeBytes > int(self.settings.material_preview_image_max_size_bytes):
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="单张预览图不能超过 5MB")
        if role_counts["MATERIAL"] > 1 or role_counts["PREVIEW"] > 10 or role_counts["CUSTOM_PREVIEW"] > 5:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="本次上传文件数量不符合要求")
        return normalized

    @staticmethod
    def descriptor_digest(files: Sequence[UploadFileDescriptorPayload]) -> str:
        serialized = json.dumps(
            [
                {
                    "contentType": "" if item.role == "MATERIAL" else item.contentType.strip().lower(),
                    "name": item.name.strip(),
                    "role": item.role,
                    "sizeBytes": int(item.sizeBytes),
                }
                for item in files
            ],
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(serialized.encode()).hexdigest()

    def reset(self) -> None:
        with self._lock:
            self._local_tickets.clear()
            self._local_reservations.clear()
            self._local_quotas.clear()
        self._redis_client = None

    def _authorize_local(
        self,
        *,
        token: str,
        token_key: str,
        user_id: int,
        submission_id: str,
        descriptor_digest: str,
        total_bytes: int,
        ttl: int,
    ) -> MaterialUploadAuthorizationResponsePayload:
        now = time()
        quota_key = self._quota_key(user_id)
        reservation_key = self._reservation_key(user_id, submission_id)
        with self._lock:
            self._purge_local(now)
            reservation = self._local_reservations.get(reservation_key)
            if reservation is not None and reservation.descriptor_digest != descriptor_digest:
                self._raise_issue_error(-4)
            if reservation is not None and reservation.active_ticket_key:
                self._local_tickets.pop(reservation.active_ticket_key, None)
            active_count = sum(
                1 for ticket in self._local_tickets.values() if ticket.user_id == user_id and not ticket.used
            )
            if active_count >= int(self.settings.upload_max_concurrent_authorizations):
                self._raise_issue_error(-3)
            count, byte_count, quota_expiry = self._local_quotas.get(quota_key, (0, 0, now + 172800))
            if reservation is None:
                if count + 1 > int(self.settings.upload_daily_submission_limit):
                    self._raise_issue_error(-1)
                if byte_count + total_bytes > int(self.settings.upload_daily_bytes_limit):
                    self._raise_issue_error(-2)
                count += 1
                byte_count += total_bytes
                self._local_quotas[quota_key] = (count, byte_count, quota_expiry)
            self._local_tickets[token_key] = _LocalUploadTicket(
                user_id=user_id,
                submission_id=submission_id,
                descriptor_digest=descriptor_digest,
                expires_at=now + ttl,
            )
            self._local_reservations[reservation_key] = _LocalReservation(
                descriptor_digest=descriptor_digest,
                total_bytes=total_bytes,
                active_ticket_key=token_key,
                expires_at=quota_expiry,
            )
            return MaterialUploadAuthorizationResponsePayload(
                uploadToken=token,
                expiresInSeconds=ttl,
                remainingDailySubmissions=max(0, int(self.settings.upload_daily_submission_limit) - count),
                remainingDailyBytes=max(0, int(self.settings.upload_daily_bytes_limit) - byte_count),
            )

    def _consume_local(self, ticket_key: str, *, user_id: int, submission_id: str, descriptor_digest: str) -> None:
        now = time()
        with self._lock:
            self._purge_local(now)
            ticket = self._local_tickets.get(ticket_key)
            if ticket is None:
                self._raise_consume_error(-1)
            if ticket.used:
                self._raise_consume_error(-2)
            if (
                ticket.user_id != user_id
                or ticket.submission_id != submission_id
                or ticket.descriptor_digest != descriptor_digest
            ):
                self._raise_consume_error(-3)
            ticket.used = True
            ticket.expires_at = now + max(30, int(self.settings.upload_authorization_consumed_marker_ttl_seconds))
            reservation = self._local_reservations.get(self._reservation_key(user_id, submission_id))
            if reservation and reservation.active_ticket_key == ticket_key:
                reservation.active_ticket_key = None

    def _purge_local(self, now: float) -> None:
        for key in [key for key, value in self._local_tickets.items() if value.expires_at <= now]:
            self._local_tickets.pop(key, None)
        for key in [key for key, value in self._local_reservations.items() if value.expires_at <= now]:
            self._local_reservations.pop(key, None)
        for key in [key for key, value in self._local_quotas.items() if value[2] <= now]:
            self._local_quotas.pop(key, None)

    def _to_response(self, token: str, ttl: int, result: Sequence[object]) -> MaterialUploadAuthorizationResponsePayload:
        outcome = int(result[0])
        if outcome != 1:
            self._raise_issue_error(outcome)
        return MaterialUploadAuthorizationResponsePayload(
            uploadToken=token,
            expiresInSeconds=ttl,
            remainingDailySubmissions=max(0, int(result[1])),
            remainingDailyBytes=max(0, int(result[2])),
        )

    @staticmethod
    def _raise_issue_error(outcome: int) -> NoReturn:
        if outcome == -1:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="今日投稿次数已达上限")
        if outcome == -2:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="今日上传总量已达上限")
        if outcome == -3:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="当前进行中的上传过多，请稍后再试")
        if outcome == -4:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="同一次投稿的文件已发生变化，请重新开始投稿")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="上传授权暂时不可用")

    @staticmethod
    def _raise_consume_error(outcome: int) -> None:
        if outcome == 1:
            return
        if outcome == -2:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="上传授权已使用，请重新获取")
        if outcome == -3:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传内容与授权不一致，请重新提交")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="上传授权不存在或已过期，请重新提交")

    @staticmethod
    def _raise_unavailable(exc: Exception) -> NoReturn:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="上传授权服务暂时不可用，请稍后再试") from exc

    def _backend(self) -> str:
        backend = (self.settings.security_state_backend or "auto").strip().lower()
        if backend == "auto":
            return "redis" if self.settings.redis_url else "local"
        return backend if backend in {"local", "redis"} else "local"

    def _client(self) -> Any:
        if self._redis_client is None:
            self._redis_client = create_redis_client(self.settings)
        return self._redis_client

    def _quota_key(self, user_id: int) -> str:
        day = datetime.now(UTC).strftime("%Y%m%d")
        return f"{redis_namespace(self.settings)}:upload:quota:{user_id}:{day}"

    def _reservation_key(self, user_id: int, submission_id: str) -> str:
        digest = hashlib.sha256(submission_id.encode()).hexdigest()
        return f"{redis_namespace(self.settings)}:upload:reservation:{user_id}:{digest}"

    def _active_key(self, user_id: int) -> str:
        return f"{redis_namespace(self.settings)}:upload:active:{user_id}"

    def _ticket_key(self, token_digest: str) -> str:
        return f"{redis_namespace(self.settings)}:upload:ticket:{token_digest}"

    @staticmethod
    def _token_digest(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()
