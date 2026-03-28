from __future__ import annotations

import base64
from io import BytesIO
import json
import zipfile

import pytest
from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient

from app.core.upload_validation import validate_file_size
from app.services.auth_service import AuthService
from tests.support import build_auth_headers, seed_read_users


PNG_1X1 = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+c86sAAAAASUVORK5CYII=")
SVG_BYTES = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"


def _zip_bytes(name: str, content: str) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, content)
    return buffer.getvalue()


def _payload_part(payload: dict[str, object]) -> tuple[str, str, str]:
    return ("payload.json", json.dumps(payload, ensure_ascii=False), "application/json")


def test_material_custom_preview_uses_signed_url(
    client: TestClient,
    auth_service: AuthService,
) -> None:
    seed_read_users(auth_service)
    alice_headers = build_auth_headers(1, 1)

    response = client.post(
        "/api/materials",
        headers=alice_headers,
        files=[
            ("payload", _payload_part(
                {
                    "title": "安全测试资料",
                    "description": "校验自定义预览签名链接",
                    "price": 0,
                    "school": "电子科技大学",
                    "college": "信通",
                    "major": "通信",
                    "gradeType": "STAGE",
                    "gradeValue": "大三",
                    "generalCourse": False,
                    "courseCategory": "MAJOR",
                    "tags": "期末速成",
                    "deliveryMethod": "FILE",
                    "previewWatermarkEnabled": True,
                    "previewSource": "MANUAL",
                    "customPreviewText": "安全测试",
                    "copyrightOwner": "Alice",
                }
            )),
            ("zip", ("safe.zip", _zip_bytes("readme.txt", "safe"), "application/zip")),
            ("previews", ("preview.png", PNG_1X1, "image/png")),
            ("customPreviews", ("custom.png", PNG_1X1, "image/png")),
        ],
    )
    assert response.status_code == 200
    detail = response.json()["data"]
    custom_url = detail["customPreviewImages"][0]
    assert "?token=" in custom_url

    signed_response = client.get(custom_url)
    assert signed_response.status_code == 200
    assert signed_response.headers["content-type"].startswith("image/png")

    naked_response = client.get(f"/api/materials/{detail['id']}/assets/custom/1")
    assert naked_response.status_code == 400

    invalid_response = client.get(f"/api/materials/{detail['id']}/assets/custom/1?token=bad-token")
    assert invalid_response.status_code == 403


def test_upload_guards_reject_non_image_market_custom_preview_and_payout_qr(
    client: TestClient,
    auth_service: AuthService,
) -> None:
    seed_read_users(auth_service)
    alice_headers = build_auth_headers(1, 1)

    market_response = client.post(
        "/api/market",
        headers=alice_headers,
        data={
            "payload": json.dumps(
                {
                    "title": "恶意 SVG",
                    "category": "DIGITAL",
                    "description": "test",
                    "price": 10,
                    "contactType": "WECHAT",
                    "contactValue": "safe-contact",
                    "school": "电子科技大学",
                },
                ensure_ascii=False,
            )
        },
        files=[("images", ("evil.svg", SVG_BYTES, "image/svg+xml"))],
    )
    assert market_response.status_code == 400
    assert "仅支持" in market_response.json()["msg"]

    material_response = client.post(
        "/api/materials",
        headers=alice_headers,
        files=[
            ("payload", _payload_part(
                {
                    "title": "恶意配图资料",
                    "description": "test",
                    "price": 0,
                    "school": "电子科技大学",
                    "college": "信通",
                    "major": "通信",
                    "gradeType": "STAGE",
                    "gradeValue": "大三",
                    "generalCourse": False,
                    "courseCategory": "MAJOR",
                    "tags": "期末速成",
                    "deliveryMethod": "FILE",
                    "previewWatermarkEnabled": True,
                    "previewSource": "MANUAL",
                    "customPreviewText": "test",
                    "copyrightOwner": "Alice",
                }
            )),
            ("zip", ("safe.zip", _zip_bytes("readme.txt", "safe"), "application/zip")),
            ("previews", ("preview.png", PNG_1X1, "image/png")),
            ("customPreviews", ("evil.svg", SVG_BYTES, "image/svg+xml")),
        ],
    )
    assert material_response.status_code == 400
    assert "仅支持" in material_response.json()["msg"]

    payout_qr_response = client.post(
        "/api/me/payout-qr",
        headers=alice_headers,
        files={"file": ("evil.svg", SVG_BYTES, "image/svg+xml")},
    )
    assert payout_qr_response.status_code == 400
    assert "仅支持" in payout_qr_response.json()["msg"]


def test_file_size_validator_rejects_oversized_material_upload() -> None:
    upload = UploadFile(filename="oversized.zip", file=BytesIO(b"x" * 11))

    with pytest.raises(HTTPException, match="资料文件不能超过 50MB"):
        validate_file_size(
            upload,
            max_size_bytes=10,
            too_large_detail="资料文件不能超过 50MB",
        )
