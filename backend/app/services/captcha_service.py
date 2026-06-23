from __future__ import annotations

import base64
import io
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from app.core.config import Settings
from app.core.exceptions import BizException
from app.schemas.auth import CaptchaResponsePayload


@dataclass(slots=True)
class CaptchaEntry:
    code: str
    expires_at: datetime


class CaptchaService:
    _GET_DELETE_SCRIPT = """
local value = redis.call('GET', KEYS[1])
if value then
  redis.call('DEL', KEYS[1])
end
return value
"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._store: dict[str, CaptchaEntry] = {}
        self._redis_client: Any | None = None

    def generate(self) -> CaptchaResponsePayload:
        code = self._generate_code()
        captcha_id = secrets.token_urlsafe(18)
        ttl_seconds = max(60, int(self.settings.captcha_ttl_seconds))
        expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
        self._store_local(captcha_id, code, expires_at)
        if self._backend() == "redis":
            try:
                self._redis_set(captcha_id, code, ttl_seconds)
            except Exception:
                pass
        return CaptchaResponsePayload(
            captchaId=captcha_id,
            imageBase64=self._render_png(code),
        )

    def validate(self, captcha_id: str | None, captcha_code: str | None) -> None:
        captcha_key = captcha_id or ""
        entry = self._pop(captcha_key)
        now = datetime.now(UTC)
        if entry is None or entry.expires_at < now:
            raise BizException("CAPTCHA_EXPIRED", "验证码已失效，请重新获取")
        if not captcha_code or entry.code.lower() != captcha_code.strip().lower():
            raise BizException("CAPTCHA_MISMATCH", "验证码错误")

    def peek_code_for_testing(self, captcha_id: str) -> str | None:
        entry = self._store.get(captcha_id)
        if entry is not None:
            return entry.code
        if self._backend() != "redis":
            return None
        try:
            return self._redis_get(captcha_id)
        except Exception:
            return None

    def reset(self) -> None:
        self._store.clear()
        if self._backend() == "redis":
            try:
                self._redis_clear()
            except Exception:
                pass
        self._redis_client = None

    def _generate_code(self) -> str:
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        return "".join(secrets.choice(alphabet) for _ in range(max(4, self.settings.captcha_code_length)))

    def _cleanup(self) -> None:
        now = datetime.now(UTC)
        expired_ids = [key for key, entry in self._store.items() if entry.expires_at < now]
        for key in expired_ids:
            self._store.pop(key, None)

    def _store_local(self, captcha_id: str, code: str, expires_at: datetime) -> None:
        self._cleanup()
        self._store[captcha_id] = CaptchaEntry(code=code, expires_at=expires_at)

    def _pop(self, captcha_id: str) -> CaptchaEntry | None:
        if self._backend() == "redis":
            try:
                entry = self._redis_pop(captcha_id)
                if entry is not None:
                    self._store.pop(captcha_id, None)
                    return entry
            except Exception:
                pass
        return self._store.pop(captcha_id, None)

    def _backend(self) -> str:
        backend = (self.settings.captcha_backend or "auto").strip().lower()
        if backend == "auto":
            return "redis" if self.settings.redis_url else "local"
        if backend == "redis" and not self.settings.redis_url:
            return "local"
        return backend if backend in {"local", "redis"} else "local"

    def _redis_key(self, captcha_id: str) -> str:
        namespace = self.settings.redis_namespace.strip(":") or "studyhub-fastapi"
        return f"{namespace}:captcha:{captcha_id}"

    def _redis_set(self, captcha_id: str, code: str, ttl_seconds: int) -> None:
        payload = json.dumps({"code": code}, separators=(",", ":"))
        self._client().set(self._redis_key(captcha_id), payload, ex=ttl_seconds)

    def _redis_get(self, captcha_id: str) -> str | None:
        raw_value = self._client().get(self._redis_key(captcha_id))
        return self._decode_redis_code(raw_value)

    def _redis_pop(self, captcha_id: str) -> CaptchaEntry | None:
        raw_value = self._client().eval(self._GET_DELETE_SCRIPT, 1, self._redis_key(captcha_id))
        code = self._decode_redis_code(raw_value)
        if code is None:
            return None
        return CaptchaEntry(code=code, expires_at=datetime.now(UTC) + timedelta(seconds=max(1, int(self.settings.captcha_ttl_seconds))))

    def _redis_clear(self) -> None:
        client = self._client()
        namespace = self.settings.redis_namespace.strip(":") or "studyhub-fastapi"
        keys = list(client.scan_iter(match=f"{namespace}:captcha:*", count=100))
        if keys:
            client.delete(*keys)

    def _decode_redis_code(self, raw_value: object) -> str | None:
        if raw_value is None:
            return None
        if isinstance(raw_value, bytes):
            raw_text = raw_value.decode("utf-8")
        else:
            raw_text = str(raw_value)
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError:
            return None
        code = payload.get("code") if isinstance(payload, dict) else None
        return str(code) if code else None

    def _client(self):
        if self._redis_client is not None:
            return self._redis_client
        if not self.settings.redis_url:
            raise RuntimeError("Redis captcha backend requires redis_url")
        import redis  # type: ignore[import-not-found]

        self._redis_client = redis.Redis.from_url(
            self.settings.redis_url,
            socket_timeout=self.settings.redis_socket_timeout_seconds,
            socket_connect_timeout=self.settings.redis_connect_timeout_seconds,
        )
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
