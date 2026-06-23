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


def test_preflight_reports_multiple_external_site_origins_as_warning() -> None:
    settings = Settings(
        environment="local-dev",
        public_site_base_url="https://study-hub.store",
        trusted_site_origins="https://study-hub.cn,https://study-hub.store",
        alipay_return_url="https://study-hub.store/pay/result",
        alipay_notify_url="https://study-hub.store/api/pay/alipay/notify",
    )

    checks = build_checks(settings, check_network=False, timeout_seconds=0.5)
    origin_check = next(item for item in checks if item.name == "site-origin-consistency")

    assert origin_check.ok is True
    assert origin_check.level == "warning"
    assert "multiple external site origins configured" in origin_check.message
    assert "https://study-hub.cn" in origin_check.message
    assert "https://study-hub.store" in origin_check.message


def test_preflight_accepts_single_external_site_origin() -> None:
    settings = Settings(
        environment="local-dev",
        public_site_base_url="https://study-hub.cn",
        trusted_site_origins="https://study-hub.cn",
        alipay_return_url="https://study-hub.cn/pay/result",
        alipay_notify_url="https://study-hub.cn/api/pay/alipay/notify",
    )

    checks = build_checks(settings, check_network=False, timeout_seconds=0.5)
    origin_check = next(item for item in checks if item.name == "site-origin-consistency")

    assert origin_check.ok is True
    assert origin_check.level == "info"
    assert "https://study-hub.cn" in origin_check.message


def test_preflight_reports_csp_report_only_rollout_stage() -> None:
    settings = Settings(
        environment="production",
        database_url="mysql+pymysql://user:pass@127.0.0.1:3306/studyhub",
        jwt_secret="production-secret-abcdefghijklmnopqrstuvwxyz",
        trusted_hosts="study-hub.cn",
    )

    checks = build_checks(settings, check_network=False, timeout_seconds=0.5)
    csp_check = next(item for item in checks if item.name == "csp-rollout")

    assert csp_check.ok is True
    assert csp_check.level == "warning"
    assert "Report-Only" in csp_check.message


def test_preflight_timeout_seconds_must_be_positive() -> None:
    settings = Settings(environment="local-dev")

    with pytest.raises(RuntimeError, match="大于 0"):
        run_preflight(settings, check_network=False, timeout_seconds=0)


def test_preflight_parser_rejects_invalid_timeout_seconds() -> None:
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["--timeout-seconds", "-1"])
