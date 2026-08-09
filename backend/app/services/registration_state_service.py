from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import secrets
from threading import RLock
from time import time
from typing import Any, NoReturn

from fastapi import HTTPException, status

from app.core.config import Settings
from app.core.redis_client import create_redis_client, redis_namespace


@dataclass(frozen=True, slots=True)
class RegistrationVerificationIssue:
    email: str
    username: str
    password_hash: str
    code: str
    expires_in_seconds: int
    resend_after_seconds: int


@dataclass(frozen=True, slots=True)
class RegistrationCredentials:
    email: str
    username: str
    password_hash: str


@dataclass(slots=True)
class _LocalPendingRegistration:
    email: str
    username: str
    password_hash: str
    code_digest: str
    attempts: int
    max_attempts: int
    sent_at: float
    expires_at: float


@dataclass(slots=True)
class _LocalRegistrationTicket:
    credentials: RegistrationCredentials
    expires_at: float
    used: bool = False


class RegistrationStateService:
    _CREATE_PENDING_SCRIPT = """
local sent_at = tonumber(redis.call('HGET', KEYS[1], 'sent_at') or '0')
local now = tonumber(ARGV[1])
local resend_after = tonumber(ARGV[2])
if sent_at > 0 and now - sent_at < resend_after then
  return {0, math.ceil(resend_after - (now - sent_at))}
end
redis.call('HSET', KEYS[1],
  'email', ARGV[3],
  'username', ARGV[4],
  'password_hash', ARGV[5],
  'code_digest', ARGV[6],
  'attempts', 0,
  'max_attempts', ARGV[7],
  'stage', 'email_sent',
  'sent_at', ARGV[1])
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[8]))
return {1, tonumber(ARGV[8])}
"""

    _ISSUE_TICKET_SCRIPT = """
if redis.call('EXISTS', KEYS[1]) == 0 then
  return {-1, 0}
end
local attempts = tonumber(redis.call('HGET', KEYS[1], 'attempts') or '0')
local max_attempts = tonumber(redis.call('HGET', KEYS[1], 'max_attempts') or '1')
if attempts >= max_attempts then
  redis.call('DEL', KEYS[1])
  return {-2, 0}
end
if redis.call('HGET', KEYS[1], 'code_digest') ~= ARGV[1] then
  attempts = redis.call('HINCRBY', KEYS[1], 'attempts', 1)
  if attempts >= max_attempts then
    redis.call('DEL', KEYS[1])
    return {-2, 0}
  end
  return {0, max_attempts - attempts}
end
local values = redis.call('HMGET', KEYS[1], 'email', 'username', 'password_hash')
redis.call('HSET', KEYS[2],
  'email', values[1],
  'username', values[2],
  'password_hash', values[3],
  'stage', 'email_verified',
  'used', 0,
  'issued_at', ARGV[2])
redis.call('EXPIRE', KEYS[2], tonumber(ARGV[3]))
redis.call('DEL', KEYS[1])
return {1, tonumber(ARGV[3])}
"""

    _CONSUME_TICKET_SCRIPT = """
if redis.call('EXISTS', KEYS[1]) == 0 then
  return {-1}
end
if redis.call('HGET', KEYS[1], 'used') == '1' then
  return {-2}
end
local values = redis.call('HMGET', KEYS[1], 'email', 'username', 'password_hash')
if not values[1] or not values[2] or not values[3] then
  redis.call('DEL', KEYS[1])
  return {-1}
end
redis.call('HSET', KEYS[1], 'used', 1, 'stage', 'consumed', 'used_at', ARGV[1])
redis.call('HDEL', KEYS[1], 'email', 'username', 'password_hash')
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
return {1, values[1], values[2], values[3]}
"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._redis_client: Any | None = None
        self._local_pending: dict[str, _LocalPendingRegistration] = {}
        self._local_tickets: dict[str, _LocalRegistrationTicket] = {}
        self._test_codes: dict[str, str] = {}
        self._lock = RLock()

    def create_verification(self, *, email: str, username: str, password_hash: str) -> RegistrationVerificationIssue:
        code = self._generate_code()
        code_digest = self._code_digest(email, code)
        ttl = max(60, int(self.settings.verification_ttl_seconds))
        resend_after = max(1, int(self.settings.verification_resend_after_seconds))
        now = time()
        pending_key = self._pending_key(email)
        if self._backend() == "redis":
            try:
                result = self._client().eval(
                    self._CREATE_PENDING_SCRIPT,
                    1,
                    pending_key,
                    now,
                    resend_after,
                    email,
                    username,
                    password_hash,
                    code_digest,
                    max(1, int(self.settings.verification_max_attempts)),
                    ttl,
                )
            except Exception as exc:  # noqa: BLE001
                self._raise_unavailable(exc)
            if int(result[0]) != 1:
                retry_after = max(1, int(result[1]))
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"验证码发送频繁，请在 {retry_after} 秒后再试",
                )
        else:
            self._create_local_pending(
                pending_key,
                email=email,
                username=username,
                password_hash=password_hash,
                code_digest=code_digest,
                now=now,
                ttl=ttl,
                resend_after=resend_after,
            )
        if self.settings.environment.strip().lower() in {"test", "local-dev"}:
            self._test_codes[pending_key] = code
        return RegistrationVerificationIssue(
            email=email,
            username=username,
            password_hash=password_hash,
            code=code,
            expires_in_seconds=ttl,
            resend_after_seconds=resend_after,
        )

    def issue_ticket(self, *, email: str, code: str) -> tuple[str, int]:
        token = secrets.token_urlsafe(32)
        token_digest = self._token_digest(token)
        ttl = max(60, int(self.settings.registration_ticket_ttl_seconds))
        pending_key = self._pending_key(email)
        ticket_key = self._ticket_key(token_digest)
        if self._backend() == "redis":
            try:
                result = self._client().eval(
                    self._ISSUE_TICKET_SCRIPT,
                    2,
                    pending_key,
                    ticket_key,
                    self._code_digest(email, code),
                    time(),
                    ttl,
                )
            except Exception as exc:  # noqa: BLE001
                self._raise_unavailable(exc)
            outcome = int(result[0])
            if outcome == 1:
                self._test_codes.pop(pending_key, None)
                return token, int(result[1])
            self._raise_code_error(outcome)
        return self._issue_local_ticket(pending_key, ticket_key, email=email, code=code, token=token, ttl=ttl)

    def consume_ticket(self, token: str) -> RegistrationCredentials:
        normalized = (token or "").strip()
        if not normalized:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="注册凭证不存在或已过期")
        ticket_key = self._ticket_key(self._token_digest(normalized))
        if self._backend() == "redis":
            try:
                result = self._client().eval(
                    self._CONSUME_TICKET_SCRIPT,
                    1,
                    ticket_key,
                    time(),
                    max(30, int(self.settings.registration_consumed_marker_ttl_seconds)),
                )
            except Exception as exc:  # noqa: BLE001
                self._raise_unavailable(exc)
            outcome = int(result[0])
            if outcome == -2:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="注册凭证已使用")
            if outcome != 1:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="注册凭证不存在或已过期")
            return RegistrationCredentials(
                email=self._decode(result[1]),
                username=self._decode(result[2]),
                password_hash=self._decode(result[3]),
            )
        return self._consume_local_ticket(ticket_key)

    def peek_code_for_testing(self, email: str) -> str | None:
        return self._test_codes.get(self._pending_key(email))

    def reset(self) -> None:
        with self._lock:
            self._local_pending.clear()
            self._local_tickets.clear()
            self._test_codes.clear()
        self._redis_client = None

    def _create_local_pending(
        self,
        pending_key: str,
        *,
        email: str,
        username: str,
        password_hash: str,
        code_digest: str,
        now: float,
        ttl: int,
        resend_after: int,
    ) -> None:
        with self._lock:
            self._purge_local(now)
            existing = self._local_pending.get(pending_key)
            if existing is not None and now - existing.sent_at < resend_after:
                retry_after = max(1, int(resend_after - (now - existing.sent_at)))
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"验证码发送频繁，请在 {retry_after} 秒后再试",
                )
            self._local_pending[pending_key] = _LocalPendingRegistration(
                email=email,
                username=username,
                password_hash=password_hash,
                code_digest=code_digest,
                attempts=0,
                max_attempts=max(1, int(self.settings.verification_max_attempts)),
                sent_at=now,
                expires_at=now + ttl,
            )

    def _issue_local_ticket(
        self,
        pending_key: str,
        ticket_key: str,
        *,
        email: str,
        code: str,
        token: str,
        ttl: int,
    ) -> tuple[str, int]:
        now = time()
        with self._lock:
            self._purge_local(now)
            pending = self._local_pending.get(pending_key)
            if pending is None or pending.expires_at <= now:
                self._local_pending.pop(pending_key, None)
                self._raise_code_error(-1)
            if pending.attempts >= pending.max_attempts:
                self._local_pending.pop(pending_key, None)
                self._raise_code_error(-2)
            if not hmac.compare_digest(pending.code_digest, self._code_digest(email, code)):
                pending.attempts += 1
                if pending.attempts >= pending.max_attempts:
                    self._local_pending.pop(pending_key, None)
                    self._raise_code_error(-2)
                self._raise_code_error(0)
            credentials = RegistrationCredentials(pending.email, pending.username, pending.password_hash)
            self._local_tickets[ticket_key] = _LocalRegistrationTicket(credentials, now + ttl)
            self._local_pending.pop(pending_key, None)
            self._test_codes.pop(pending_key, None)
            return token, ttl

    def _consume_local_ticket(self, ticket_key: str) -> RegistrationCredentials:
        now = time()
        with self._lock:
            self._purge_local(now)
            ticket = self._local_tickets.get(ticket_key)
            if ticket is None or ticket.expires_at <= now:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="注册凭证不存在或已过期")
            if ticket.used:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="注册凭证已使用")
            ticket.used = True
            ticket.expires_at = now + max(30, int(self.settings.registration_consumed_marker_ttl_seconds))
            return ticket.credentials

    def _purge_local(self, now: float) -> None:
        for key in [key for key, value in self._local_pending.items() if value.expires_at <= now]:
            self._local_pending.pop(key, None)
            self._test_codes.pop(key, None)
        for key in [key for key, value in self._local_tickets.items() if value.expires_at <= now]:
            self._local_tickets.pop(key, None)

    def _raise_code_error(self, outcome: int) -> NoReturn:
        if outcome == -2:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码错误次数过多，请重新获取")
        if outcome == 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码错误")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码不存在或已过期")

    def _raise_unavailable(self, exc: Exception) -> NoReturn:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="安全验证服务暂时不可用，请稍后再试",
        ) from exc

    def _generate_code(self) -> str:
        value = secrets.randbelow(10 ** int(self.settings.verification_code_length))
        return str(value).zfill(int(self.settings.verification_code_length))

    def _code_digest(self, email: str, code: str) -> str:
        message = f"registration:{email.strip().lower()}:{(code or '').strip()}".encode()
        return hmac.new(self.settings.jwt_secret.encode(), message, hashlib.sha256).hexdigest()

    def _pending_key(self, email: str) -> str:
        digest = hashlib.sha256(email.strip().lower().encode()).hexdigest()
        return f"{redis_namespace(self.settings)}:registration:pending:{digest}"

    def _ticket_key(self, token_digest: str) -> str:
        return f"{redis_namespace(self.settings)}:registration:ticket:{token_digest}"

    @staticmethod
    def _token_digest(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def _backend(self) -> str:
        backend = (self.settings.security_state_backend or "auto").strip().lower()
        if backend == "auto":
            return "redis" if self.settings.redis_url else "local"
        if backend == "redis" and not self.settings.redis_url:
            return "redis"
        return backend if backend in {"local", "redis"} else "local"

    def _client(self) -> Any:
        if self._redis_client is None:
            self._redis_client = create_redis_client(self.settings)
        return self._redis_client

    @staticmethod
    def _decode(value: object) -> str:
        return value.decode("utf-8") if isinstance(value, bytes) else str(value)
