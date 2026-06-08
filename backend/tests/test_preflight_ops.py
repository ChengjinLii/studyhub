from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import Settings
from app.ops.preflight import build_checks, build_parser, run_preflight


def test_preflight_accepts_existing_alipay_files(tmp_path: Path) -> None:
    private_key = tmp_path / "app_private_key.pem"
    public_key = tmp_path / "alipay_public_key.pem"
    private_key.write_text("private", encoding="utf-8")
    public_key.write_text("public", encoding="utf-8")

    settings = Settings(
        environment="local-dev",
        database_url="mysql+pymysql://user:pass@127.0.0.1:3306/studyhub",
        jwt_secret="preview-secret-abcdefghijklmnopqrstuvwxyz",
        payment_provider="alipay_page",
        payout_transfer_provider="local_transfer",
        alipay_app_private_key_path=str(private_key),
        alipay_public_key_path=str(public_key),
    )

    payload = run_preflight(settings, check_network=False, timeout_seconds=0.5)

    assert payload["ok"] is True


def test_preflight_reports_missing_alipay_private_key(tmp_path: Path) -> None:
    public_key = tmp_path / "alipay_public_key.pem"
    public_key.write_text("public", encoding="utf-8")

    settings = Settings(
        environment="local-dev",
        database_url="mysql+pymysql://user:pass@127.0.0.1:3306/studyhub",
        jwt_secret="preview-secret-abcdefghijklmnopqrstuvwxyz",
        payment_provider="alipay_page",
        payout_transfer_provider="local_transfer",
        alipay_app_private_key_path=str(tmp_path / "missing.pem"),
        alipay_public_key_path=str(public_key),
    )

    checks = build_checks(settings, check_network=False, timeout_seconds=0.5)
    private_key_check = next(item for item in checks if item.name == "alipay-app-private-key")

    assert private_key_check.ok is False
    assert "file not found" in private_key_check.message


def test_preflight_timeout_seconds_must_be_positive() -> None:
    settings = Settings(environment="local-dev")

    with pytest.raises(RuntimeError, match="大于 0"):
        run_preflight(settings, check_network=False, timeout_seconds=0)


def test_preflight_parser_rejects_invalid_timeout_seconds() -> None:
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["--timeout-seconds", "-1"])
