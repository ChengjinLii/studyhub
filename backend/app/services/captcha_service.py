from __future__ import annotations

import base64
import hashlib
import hmac
import io
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from app.core.config import Settings
from app.core.exceptions import BizException
from app.core.redis_client import create_redis_client, redis_namespace
from app.schemas.auth import CaptchaResponsePayload


@dataclass(slots=True)
class CaptchaEntry:
    code_digest: str
    expires_at: datetime
    attempts: int = 0


class CaptchaService:
    _VALIDATE_SCRIPT = """
if redis.call('EXISTS', KEYS[1]) == 0 then
  return -1
end
local attempts = tonumber(redis.call('HGET', KEYS[1], 'attempts') or '0')
local max_attempts = tonumber(redis.call('HGET', KEYS[1], 'max_attempts') or '1')
if attempts >= max_attempts then
  redis.call('DEL', KEYS[1])
  return -2
end
if redis.call('HGET', KEYS[1], 'code_digest') ~= ARGV[1] then
  attempts = redis.call('HINCRBY', KEYS[1], 'attempts', 1)
  if attempts >= max_attempts then
    redis.call('DEL', KEYS[1])
    return -2
  end
  return 0
end
redis.call('DEL', KEYS[1])
return 1
"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._store: dict[str, CaptchaEntry] = {}
        self._test_codes: dict[str, str] = {}
        self._redis_client: Any | None = None
        self._lock = RLock()

    def generate(self) -> CaptchaResponsePayload:
        code = self._generate_code()
        captcha_id = secrets.token_urlsafe(18)
        ttl_seconds = max(60, int(self.settings.captcha_ttl_seconds))
        expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
        digest = self._code_digest(captcha_id, code)
        self._store_local(captcha_id, digest, expires_at)
        if self.settings.environment.strip().lower() in {"test", "local-dev"}:
            self._test_codes[captcha_id] = code
        if self._backend() == "redis":
            try:
                self._redis_set(captcha_id, digest, ttl_seconds)
            except Exception:
                # Login and registration retain the existing single-process
                # image-CAPTCHA fallback when Redis is temporarily unavailable.
                pass
        return CaptchaResponsePayload(captchaId=captcha_id, imageBase64=self._render_png(code))

    def validate(self, captcha_id: str | None, captcha_code: str | None) -> None:
        captcha_key = (captcha_id or "").strip()
        submitted_digest = self._code_digest(captcha_key, captcha_code or "")
        if self._backend() == "redis":
            try:
                outcome = int(self._client().eval(self._VALIDATE_SCRIPT, 1, self._redis_key(captcha_key), submitted_digest))
            except Exception:
                outcome = self._validate_local(captcha_key, submitted_digest)
            else:
                self._mirror_redis_outcome(captcha_key, outcome)
        else:
            outcome = self._validate_local(captcha_key, submitted_digest)
        self._raise_for_outcome(outcome)

    def peek_code_for_testing(self, captcha_id: str) -> str | None:
        return self._test_codes.get(captcha_id)

    def reset(self) -> None:
        with self._lock:
            self._store.clear()
            self._test_codes.clear()
        if self._backend() == "redis":
            try:
                self._redis_clear()
            except Exception:
                pass
        self._redis_client = None

    def _generate_code(self) -> str:
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        return "".join(secrets.choice(alphabet) for _ in range(max(4, self.settings.captcha_code_length)))

    def _code_digest(self, captcha_id: str, code: str) -> str:
        normalized = (code or "").strip().upper()
        message = f"captcha:{captcha_id}:{normalized}".encode()
        return hmac.new(self.settings.jwt_secret.encode(), message, hashlib.sha256).hexdigest()

    def _cleanup_locked(self, now: datetime) -> None:
        expired_ids = [key for key, entry in self._store.items() if entry.expires_at < now]
        for key in expired_ids:
            self._store.pop(key, None)
            self._test_codes.pop(key, None)

    def _store_local(self, captcha_id: str, digest: str, expires_at: datetime) -> None:
        with self._lock:
            self._cleanup_locked(datetime.now(UTC))
            self._store[captcha_id] = CaptchaEntry(code_digest=digest, expires_at=expires_at)

    def _validate_local(self, captcha_id: str, submitted_digest: str) -> int:
        now = datetime.now(UTC)
        with self._lock:
            self._cleanup_locked(now)
            entry = self._store.get(captcha_id)
            if entry is None or entry.expires_at < now:
                self._store.pop(captcha_id, None)
                self._test_codes.pop(captcha_id, None)
                return -1
            if entry.attempts >= max(1, int(self.settings.captcha_max_attempts)):
                self._store.pop(captcha_id, None)
                self._test_codes.pop(captcha_id, None)
                return -2
            if not hmac.compare_digest(entry.code_digest, submitted_digest):
                entry.attempts += 1
                if entry.attempts >= max(1, int(self.settings.captcha_max_attempts)):
                    self._store.pop(captcha_id, None)
                    self._test_codes.pop(captcha_id, None)
                    return -2
                return 0
            self._store.pop(captcha_id, None)
            self._test_codes.pop(captcha_id, None)
            return 1

    def _mirror_redis_outcome(self, captcha_id: str, outcome: int) -> None:
        if outcome in {1, -1, -2}:
            with self._lock:
                self._store.pop(captcha_id, None)
                self._test_codes.pop(captcha_id, None)
            return
        if outcome == 0:
            with self._lock:
                entry = self._store.get(captcha_id)
                if entry is not None:
                    entry.attempts += 1

    def _raise_for_outcome(self, outcome: int) -> None:
        if outcome == 1:
            return
        if outcome == 0:
            raise BizException("CAPTCHA_MISMATCH", "验证码错误")
        if outcome == -2:
            raise BizException("CAPTCHA_ATTEMPTS_EXCEEDED", "验证码错误次数过多，请重新获取")
        raise BizException("CAPTCHA_EXPIRED", "验证码已失效，请重新获取")

    def _backend(self) -> str:
        backend = (self.settings.captcha_backend or "auto").strip().lower()
        if backend == "auto":
            return "redis" if self.settings.redis_url else "local"
        if backend == "redis" and not self.settings.redis_url:
            return "local"
        return backend if backend in {"local", "redis"} else "local"

    def _redis_key(self, captcha_id: str) -> str:
        return f"{redis_namespace(self.settings)}:captcha:{captcha_id}"

    def _redis_set(self, captcha_id: str, digest: str, ttl_seconds: int) -> None:
        key = self._redis_key(captcha_id)
        with self._client().pipeline(transaction=True) as pipe:
            pipe.hset(
                key,
                mapping={
                    "code_digest": digest,
                    "attempts": 0,
                    "max_attempts": max(1, int(self.settings.captcha_max_attempts)),
                    "kind": "image",
                },
            )
            pipe.expire(key, ttl_seconds)
            pipe.execute()

    def _redis_clear(self) -> None:
        client = self._client()
        keys = list(client.scan_iter(match=f"{redis_namespace(self.settings)}:captcha:*", count=100))
        if keys:
            client.delete(*keys)

    def _client(self) -> Any:
        if self._redis_client is None:
            self._redis_client = create_redis_client(self.settings)
        return self._redis_client

    def _render_png(self, code: str) -> str:
        image = Image.new("RGB", (140, 48), color=(249, 250, 251))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((1, 1, 138, 46), radius=10, outline=(209, 213, 219), width=1, fill=(249, 250, 251))
        font = ImageFont.load_default()
        for index, char in enumerate(code):
            draw.text((18 + index * 24, 14 + (index % 2) * 2), char, font=font, fill=(17, 24, 39))
        draw.line((10, 34, 128, 14), fill=(148, 163, 184), width=1)
        output = io.BytesIO()
        image.save(output, format="PNG")
        base64_bytes = base64.b64encode(output.getvalue()).decode("ascii")
        return f"data:image/png;base64,{base64_bytes}"
