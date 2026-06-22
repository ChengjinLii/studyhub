from __future__ import annotations

from starlette.datastructures import MutableHeaders

from app.core.config import Settings


def apply_security_headers(settings: Settings, headers: MutableHeaders) -> None:
    if not settings.security_headers_enabled:
        return
    headers.setdefault("x-content-type-options", "nosniff")
    headers.setdefault("x-frame-options", settings.security_frame_options)
    headers.setdefault("referrer-policy", settings.security_referrer_policy)
    headers.setdefault("permissions-policy", settings.security_permissions_policy)
    if settings.security_csp:
        headers.setdefault("content-security-policy", settings.security_csp)
    if settings.security_csp_report_only:
        headers.setdefault("content-security-policy-report-only", settings.security_csp_report_only)
    if settings.resolved_security_hsts_enabled:
        max_age = max(0, int(settings.security_hsts_max_age_seconds))
        headers.setdefault("strict-transport-security", f"max-age={max_age}; includeSubDomains")
