from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
import json
from pathlib import Path
import smtplib
from typing import Any, Protocol
import uuid

from app.core.config import Settings


@dataclass(slots=True)
class MailMessage:
    purpose: str
    email: str
    subject: str
    code: str
    username: str | None
    expires_in_seconds: int
    resend_after_seconds: int
    issued_at: str
    body_text: str


class MailProvider(Protocol):
    provider_name: str

    def send_verification_email(self, message: MailMessage) -> Path: ...
    async def send_verification_email_async(self, message: MailMessage) -> Path: ...

    def probe(self, *, deep: bool = False) -> dict[str, Any]: ...
    async def probe_async(self, *, deep: bool = False) -> dict[str, Any]: ...


class LocalOutboxMailProvider:
    """
    local-dev 下不接真实 SMTP，而是把邮件写入本地 outbox。

    这样前后端联调仍然保留“发邮件”这一步，但 clone 仓库的人不需要任何私密配置。
    """

    provider_name = "local_outbox"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def send_verification_email(self, message: MailMessage) -> Path:
        target_dir = self.settings.resolved_mail_outbox_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        safe_email = message.email.replace("@", "_at_").replace(".", "_")
        file_name = f"{timestamp}-{message.purpose.lower()}-{safe_email}-{uuid.uuid4().hex[:8]}.json"
        target = target_dir / file_name
        target.write_text(json.dumps(asdict(message), ensure_ascii=False, indent=2), encoding="utf-8")
        return target

    async def send_verification_email_async(self, message: MailMessage) -> Path:
        return await asyncio.to_thread(self.send_verification_email, message)

    def probe(self, *, deep: bool = False) -> dict[str, Any]:
        del deep
        return {
            "status": "ok",
            "provider": self.provider_name,
            "mode": "filesystem",
            "target": str(self.settings.resolved_mail_outbox_dir),
        }

    async def probe_async(self, *, deep: bool = False) -> dict[str, Any]:
        return await asyncio.to_thread(self.probe, deep=deep)


class SmtpMailProvider:
    provider_name = "smtp"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        if not self.settings.smtp_host or not self.settings.smtp_from_email:
            raise ValueError("SMTP provider 缺少 host 或 from_email 配置。")

    def send_verification_email(self, message: MailMessage) -> Path:
        email = EmailMessage()
        email["Subject"] = message.subject
        email["From"] = self.settings.smtp_from_email
        email["To"] = message.email
        email.set_content(message.body_text)

        if self.settings.smtp_use_ssl:
            with smtplib.SMTP_SSL(
                self.settings.smtp_host,
                self.settings.smtp_port,
                timeout=self.settings.smtp_timeout_seconds,
            ) as server:
                self._login_if_needed(server)
                server.send_message(email)
        else:
            with smtplib.SMTP(
                self.settings.smtp_host,
                self.settings.smtp_port,
                timeout=self.settings.smtp_timeout_seconds,
            ) as server:
                if self.settings.smtp_starttls:
                    server.starttls()
                self._login_if_needed(server)
                server.send_message(email)

        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        safe_email = message.email.replace("@", "_at_").replace(".", "_")
        return Path("smtp-sent") / f"{timestamp}-{safe_email}.eml"

    async def send_verification_email_async(self, message: MailMessage) -> Path:
        return await asyncio.to_thread(self.send_verification_email, message)

    def probe(self, *, deep: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": "ok",
            "provider": self.provider_name,
            "host": self.settings.smtp_host,
            "port": self.settings.smtp_port,
            "transport": "ssl" if self.settings.smtp_use_ssl else ("starttls" if self.settings.smtp_starttls else "plain"),
        }
        if not deep:
            payload["mode"] = "configured"
            return payload

        if self.settings.smtp_use_ssl:
            with smtplib.SMTP_SSL(
                self.settings.smtp_host,
                self.settings.smtp_port,
                timeout=self.settings.smtp_timeout_seconds,
            ) as server:
                code, banner = server.noop()
        else:
            with smtplib.SMTP(
                self.settings.smtp_host,
                self.settings.smtp_port,
                timeout=self.settings.smtp_timeout_seconds,
            ) as server:
                if self.settings.smtp_starttls:
                    server.starttls()
                code, banner = server.noop()
        payload["probe"] = {"code": int(code), "banner": str(banner)}
        return payload

    async def probe_async(self, *, deep: bool = False) -> dict[str, Any]:
        return await asyncio.to_thread(self.probe, deep=deep)

    def _login_if_needed(self, server: smtplib.SMTP) -> None:
        if self.settings.smtp_username:
            server.login(self.settings.smtp_username, self.settings.smtp_password or "")
