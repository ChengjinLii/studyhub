from __future__ import annotations

import base64
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app.api.deps import get_market_service, get_payout_service
from app.services.auth_service import AuthService
from tests.support import build_auth_headers, seed_read_users


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4//8/AwAI/AL+p5qgoAAAAABJRU5ErkJggg=="
)


def test_failed_market_create_removes_new_image(
    client: TestClient,
    auth_service: AuthService,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seed_read_users(auth_service)
    headers = build_auth_headers(1, 1)
    assert client.get("/api/market").status_code == 200
    service = get_market_service()

    def fail_save(*_args, **_kwargs):
        raise RuntimeError("market database write failed")

    monkeypatch.setattr(service.market_repo, "save_item", fail_save)
    payload = {
        "title": "市场图片补偿测试",
        "category": "DIGITAL",
        "description": "数据库失败后不应残留图片",
        "price": 1,
        "contactType": "QQ",
        "contactValue": "123456",
        "school": "电子科技大学",
    }

    with pytest.raises(RuntimeError, match="market database write failed"):
        client.post(
            "/api/market",
            headers=headers,
            data={"payload": json.dumps(payload, ensure_ascii=False)},
            files=[("images", ("market-fail.png", PNG_1X1, "image/png"))],
        )

    assert list((tmp_path / "market").rglob("*market-fail.png")) == []


def test_failed_payout_qr_update_keeps_old_image_and_removes_new_image(
    client: TestClient,
    auth_service: AuthService,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seed_read_users(auth_service)
    headers = build_auth_headers(2, 2)
    first = client.post(
        "/api/me/payout-qr",
        headers=headers,
        files={"file": ("old-qr.png", PNG_1X1, "image/png")},
    )
    assert first.status_code == 200
    old_paths = list((tmp_path / "payout-qr").rglob("*old-qr.png"))
    assert len(old_paths) == 1
    service = get_payout_service()

    def fail_save(*_args, **_kwargs):
        raise RuntimeError("payout database write failed")

    monkeypatch.setattr(service.auth_repo, "save_user", fail_save)
    with pytest.raises(RuntimeError, match="payout database write failed"):
        client.post(
            "/api/me/payout-qr",
            headers=headers,
            files={"file": ("new-qr.png", PNG_1X1, "image/png")},
        )

    assert old_paths[0].exists()
    assert list((tmp_path / "payout-qr").rglob("*new-qr.png")) == []
