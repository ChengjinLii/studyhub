from __future__ import annotations

import base64
import io
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from PIL import Image, ImageDraw, ImageFont

from app.core.config import Settings
from app.core.exceptions import BizException
from app.schemas.auth import CaptchaResponsePayload


@dataclass(slots=True)
class CaptchaEntry:
    code: str
    expires_at: datetime


class CaptchaService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._store: dict[str, CaptchaEntry] = {}

    def generate(self) -> CaptchaResponsePayload:
        code = self._generate_code()
        captcha_id = secrets.token_urlsafe(18)
        self._cleanup()
        self._store[captcha_id] = CaptchaEntry(
            code=code,
            expires_at=datetime.now(UTC) + timedelta(seconds=max(60, self.settings.captcha_ttl_seconds)),
        )
        return CaptchaResponsePayload(
            captchaId=captcha_id,
            imageBase64=self._render_png(code),
        )

    def validate(self, captcha_id: str | None, captcha_code: str | None) -> None:
        entry = self._store.pop(captcha_id or "", None)
        now = datetime.now(UTC)
        if entry is None or entry.expires_at < now:
            raise BizException("CAPTCHA_EXPIRED", "验证码已失效，请重新获取")
        if not captcha_code or entry.code.lower() != captcha_code.strip().lower():
            raise BizException("CAPTCHA_MISMATCH", "验证码错误")

    def peek_code_for_testing(self, captcha_id: str) -> str | None:
        entry = self._store.get(captcha_id)
        return None if entry is None else entry.code

    def reset(self) -> None:
        self._store.clear()

    def _generate_code(self) -> str:
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        return "".join(secrets.choice(alphabet) for _ in range(max(4, self.settings.captcha_code_length)))

    def _cleanup(self) -> None:
        now = datetime.now(UTC)
        expired_ids = [key for key, entry in self._store.items() if entry.expires_at < now]
        for key in expired_ids:
            self._store.pop(key, None)

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
