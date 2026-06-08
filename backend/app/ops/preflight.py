from __future__ import annotations

import argparse
import json
import math
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.engine import make_url

from app.core.config import Settings, get_settings


@dataclass(slots=True)
class CheckResult:
    name: str
    ok: bool
    message: str

    def as_dict(self) -> dict[str, object]:
        return {"name": self.name, "ok": self.ok, "message": self.message}


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


def build_checks(settings: Settings, *, check_network: bool, timeout_seconds: float) -> list[CheckResult]:
    timeout_seconds = _require_positive_timeout_seconds(timeout_seconds)
    checks = [
        CheckResult("private-env", settings.private_env_file is None or settings.private_env_file.exists(), str(settings.private_env_file or "not required")),
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
