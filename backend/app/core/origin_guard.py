from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import Request

from app.core.config import Settings


WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
AUTH_COOKIE_NAMES = ("studyhub_token=", "studyhub_user=")


def _origin_from_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def _has_studyhub_auth_cookie(request: Request) -> bool:
    cookie_header = request.headers.get("cookie") or ""
    return any(cookie_name in cookie_header for cookie_name in AUTH_COOKIE_NAMES)


def _has_bearer_auth(request: Request) -> bool:
    return request.headers.get("authorization", "").strip().lower().startswith("bearer ")


def write_origin_allowed(settings: Settings, request: Request) -> tuple[bool, str | None]:
    if not settings.resolved_write_origin_protection_enabled:
        return True, None
    if request.method.upper() not in WRITE_METHODS:
        return True, None
    if not request.url.path.startswith(settings.api_prefix):
        return True, None

    origin = request.headers.get("origin") or _origin_from_url(request.headers.get("referer"))
    if not origin:
        if settings.resolved_write_origin_require_header and _has_studyhub_auth_cookie(request) and not _has_bearer_auth(request):
            return False, "Write request origin is required"
        return True, None
    if origin in settings.resolved_trusted_site_origins:
        return True, None
    return False, "Write request origin is not allowed"
