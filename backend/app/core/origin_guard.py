from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import Request

from app.core.config import Settings


WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _origin_from_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def write_origin_allowed(settings: Settings, request: Request) -> tuple[bool, str | None]:
    if not settings.resolved_write_origin_protection_enabled:
        return True, None
    if request.method.upper() not in WRITE_METHODS:
        return True, None
    if not request.url.path.startswith(settings.api_prefix):
        return True, None

    origin = request.headers.get("origin") or _origin_from_url(request.headers.get("referer"))
    if not origin:
        return True, None
    if origin in settings.resolved_trusted_site_origins:
        return True, None
    return False, "Write request origin is not allowed"
