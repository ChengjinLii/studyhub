from __future__ import annotations

import argparse
import json
import math
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.engine import make_url

from app.core.config import Settings, get_settings


@dataclass(slots=True)
class CheckResult:
    name: str
    ok: bool
    message: str
    level: str = "error"

    def as_dict(self) -> dict[str, object]:
        return {"name": self.name, "ok": self.ok, "level": self.level, "message": self.message}


def _check_file(name: str, path_value: str | None, *, required: bool) -> CheckResult:
    if not path_value:
        return CheckResult(name, not required, "not configured" if not required else "missing configuration")
    path = Path(path_value)
    if path.exists() and path.is_file():
        return CheckResult(name, True, str(path))
    return CheckResult(name, False, f"file not found: {path}")


def _check_tcp(name: str, host: str | None, port: int | None, *, timeout_seconds: float) -> CheckResult:
    if not host or not port:
        return CheckResult(name, False, "missing host or port")
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return CheckResult(name, True, f"{host}:{port} reachable")
    except OSError as exc:
        return CheckResult(name, False, f"{host}:{port} unreachable: {exc}")


def _require_positive_timeout_seconds(timeout_seconds: float) -> float:
    value = float(timeout_seconds)
    if not math.isfinite(value) or value <= 0:
        raise RuntimeError("preflight timeout_seconds 必须是大于 0 的数字。")
    return value


def _timeout_seconds_argument(value: str) -> float:
    try:
        return _require_positive_timeout_seconds(float(value))
    except (RuntimeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("must be a positive number") from exc


def _url_origin(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def _is_external_site_origin(origin: str) -> bool:
    host = urlparse(origin).hostname or ""
    if host in {"localhost", "127.0.0.1", "::1", "testserver"}:
        return False
    if all(part.isdigit() for part in host.split(".") if part):
        return False
    return True


def _check_site_origin_consistency(settings: Settings) -> CheckResult:
    public_origin = _url_origin(settings.resolved_public_site_base_url)
    trusted_origins = {_url_origin(item) for item in settings.resolved_trusted_site_origins}
    trusted_origins.discard(None)
    payment_origins = {
        _url_origin(settings.alipay_return_url),
        _url_origin(settings.alipay_notify_url),
    }
    payment_origins.discard(None)
    configured_origins = {origin for origin in [public_origin, *trusted_origins, *payment_origins] if origin}
    external_origins = sorted(origin for origin in configured_origins if _is_external_site_origin(origin))
    warnings: list[str] = []

    if public_origin and public_origin not in trusted_origins:
        warnings.append(f"public site origin {public_origin} is not included in trusted site origins")

    missing_payment_origins = sorted(origin for origin in payment_origins if origin and origin not in trusted_origins and origin != public_origin)
    if missing_payment_origins:
        warnings.append(f"payment callback origins are not trusted: {', '.join(missing_payment_origins)}")

    if len(external_origins) > 1:
        warnings.append(f"multiple external site origins configured: {', '.join(external_origins)}")

    if warnings:
        return CheckResult("site-origin-consistency", True, "warning: " + "; ".join(warnings), level="warning")
    return CheckResult("site-origin-consistency", True, f"public origin {public_origin or 'not configured'}", level="info")


def _check_csp_rollout(settings: Settings) -> CheckResult:
    if settings.security_csp:
        return CheckResult("csp-rollout", True, "enforced Content-Security-Policy is configured", level="info")
    report_only = settings.resolved_security_csp_report_only
    if report_only:
        return CheckResult(
            "csp-rollout",
            True,
            "warning: only Content-Security-Policy-Report-Only is active; review reports before enabling enforced CSP",
            level="warning",
        )
    return CheckResult(
        "csp-rollout",
        True,
        "warning: CSP is not configured",
        level="warning",
    )


def build_checks(settings: Settings, *, check_network: bool, timeout_seconds: float) -> list[CheckResult]:
    timeout_seconds = _require_positive_timeout_seconds(timeout_seconds)
    checks = [
        CheckResult("private-env", settings.private_env_file is None or settings.private_env_file.exists(), str(settings.private_env_file or "not required")),
        _check_site_origin_consistency(settings),
        _check_csp_rollout(settings),
    ]

    if settings.payment_provider == "alipay_page" or settings.payout_transfer_provider == "alipay_transfer":
        checks.extend(
            [
                _check_file("alipay-app-private-key", settings.alipay_app_private_key_path, required=True),
                _check_file(
                    "alipay-public-key-or-cert",
                    settings.alipay_public_key_path or settings.alipay_public_cert_path,
                    required=True,
                ),
                _check_file("alipay-app-cert", settings.alipay_app_cert_path, required=False),
                _check_file("alipay-public-cert", settings.alipay_public_cert_path, required=False),
                _check_file("alipay-root-cert", settings.alipay_root_cert_path, required=False),
            ]
        )

    if check_network:
        db_url = make_url(settings.resolved_database_url)
        if db_url.get_backend_name().lower() == "mysql":
            checks.append(
                _check_tcp(
                    "mysql-tcp",
                    db_url.host,
                    int(db_url.port or 3306),
                    timeout_seconds=timeout_seconds,
                )
            )

    return checks


def run_preflight(settings: Settings, *, check_network: bool, timeout_seconds: float) -> dict[str, Any]:
    checks = build_checks(settings, check_network=check_network, timeout_seconds=timeout_seconds)
    return {
        "environment": settings.environment,
        "ok": all(item.ok for item in checks),
        "checks": [item.as_dict() for item in checks],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="StudyHub deployment preflight checks")
    parser.add_argument("--network", action="store_true", help="also check outbound TCP connectivity")
    parser.add_argument("--timeout-seconds", type=_timeout_seconds_argument, default=5.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = run_preflight(
        get_settings(),
        check_network=bool(args.network),
        timeout_seconds=float(args.timeout_seconds),
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
