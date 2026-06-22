from __future__ import annotations

import base64
from io import BytesIO
import json
import zipfile

from fastapi.testclient import TestClient

from app.core.db import session_scope
from app.models.auth import AuthUser
from app.services.auth_service import AuthService
from tests.support import build_auth_headers, seed_read_users


PNG_1X1 = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+c86sAAAAASUVORK5CYII=")


def _zip_bytes(name: str, content: str) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, content)
    return buffer.getvalue()


def _payload_part(payload: dict[str, object]) -> tuple[str, str, str]:
    return ("payload.json", json.dumps(payload, ensure_ascii=False), "application/json")


def test_step8_existing_material_flow_supports_view_preview_download_and_interactions(
    client: TestClient,
    auth_service: AuthService,
) -> None:
    seed_read_users(auth_service, with_follow_graph=True)
    alice_headers = build_auth_headers(1, 1)

    detail_response = client.get("/api/materials/101", headers=alice_headers)
    assert detail_response.status_code == 200
    detail = detail_response.json()["data"]
    assert detail["purchased"] is True
    assert detail["liked"] is True
    assert detail["favorited"] is False

    first_view = client.post("/api/materials/101/view", json={"viewerToken": "viewer-a"})
    assert first_view.status_code == 200
    assert first_view.json()["data"]["viewCount"] == 246
    second_view = client.post("/api/materials/101/view", json={"viewerToken": "viewer-a"})
    assert second_view.status_code == 200
    assert second_view.json()["data"]["viewCount"] == 246

    preview_response = client.get("/api/materials/101/preview", headers=alice_headers)
    assert preview_response.status_code == 200
    preview = preview_response.json()["data"]
    assert preview["status"] == "done"
    assert preview["previewPages"] == 3
    preview_image_response = client.get(preview["images"][0]["img"]["src"])
    assert preview_image_response.status_code == 200
    assert preview_image_response.headers["content-type"].startswith("image/svg+xml")

    unlike_response = client.delete("/api/materials/101/like", headers=alice_headers)
    assert unlike_response.status_code == 200
    assert unlike_response.json()["data"] == 30
    like_response = client.post("/api/materials/101/like", headers=alice_headers)
    assert like_response.status_code == 200
    assert like_response.json()["data"] == 31

    rating_response = client.put("/api/materials/101/rating", json={"rating": 4}, headers=alice_headers)
    assert rating_response.status_code == 200
    rating_data = rating_response.json()["data"]
    assert rating_data["rating"] == 4
    assert rating_data["ratingCount"] == 16
    assert rating_data["ratingAvg"] == 4.74

    review_response = client.post(
        "/api/materials/101/review",
        json={"rating": 5, "comment": "补充一条 Step 8 评语"},
        headers=alice_headers,
    )
    assert review_response.status_code == 200
    refreshed_detail = client.get("/api/materials/101", headers=alice_headers).json()["data"]
    assert refreshed_detail["reviews"][0]["comment"] == "补充一条 Step 8 评语"

    download_response = client.get("/api/materials/101/download", headers=alice_headers)
    assert download_response.status_code == 200
    file_response = client.get(download_response.json()["data"]["url"])
    assert file_response.status_code == 200
    assert file_response.headers["content-type"].startswith("application/pdf")
    with session_scope() as session:
        user = session.get(AuthUser, 1)
        assert user is not None
        assert user.free_download_quota == 6


def test_step8_create_update_delete_and_batch_download_support_multipart_materials(
    client: TestClient,
    auth_service: AuthService,
) -> None:
    seed_read_users(auth_service, with_follow_graph=True)
    alice_headers = build_auth_headers(1, 1)

    create_payload = {
        "title": "Step 8 新建资料",
        "description": "这是一个新的资料条目",
        "price": 0,
        "school": "电子科技大学",
        "college": "信通",
        "major": "通信",
        "gradeType": "STAGE",
        "gradeValue": "大三",
        "generalCourse": False,
        "courseCategory": "MAJOR",
        "tags": "期末速成,一页纸",
        "deliveryMethod": "FILE",
        "previewWatermarkEnabled": True,
        "previewSource": "MANUAL",
        "customPreviewText": "自定义预览文案",
        "copyrightOwner": "Alice",
    }
    create_response = client.post(
        "/api/materials",
        headers=alice_headers,
        files=[
            ("payload", _payload_part(create_payload)),
            ("zip", ("step8.zip", _zip_bytes("notes.txt", "hello step 8"), "application/zip")),
            ("previews", ("preview-1.png", PNG_1X1, "image/png")),
            ("customPreviews", ("custom-1.png", PNG_1X1, "image/png")),
        ],
    )
    assert create_response.status_code == 200
    created = create_response.json()["data"]
    material_id = created["id"]
    assert material_id > 104
    assert created["hasFile"] is True
    assert created["previewSource"] == "MANUAL"
    assert created["customPreviewImages"][0].startswith(f"/api/materials/{material_id}/assets/custom/1?token=")

    custom_preview_response = client.get(created["customPreviewImages"][0])
    assert custom_preview_response.status_code == 200
    assert custom_preview_response.headers["content-type"].startswith("image/png")
    assert client.get(f"/api/materials/{material_id}/assets/custom/1").status_code == 400

    preview_response = client.get(f"/api/materials/{material_id}/preview", headers=alice_headers)
    assert preview_response.status_code == 200
    preview = preview_response.json()["data"]
    assert preview["status"] == "done"
    assert preview["pageCount"] == 1
    preview_asset_response = client.get(preview["images"][0]["img"]["src"])
    assert preview_asset_response.status_code == 200
    assert preview_asset_response.headers["content-type"].startswith("image/png")

    download_response = client.get(f"/api/materials/{material_id}/download", headers=alice_headers)
    assert download_response.status_code == 200
    file_response = client.get(download_response.json()["data"]["url"])
    assert file_response.status_code == 200
    assert file_response.content.startswith(b"PK")

    batch_response = client.post("/api/materials/downloads/batch", json={"materialIds": [material_id, 102]}, headers=alice_headers)
    assert batch_response.status_code == 200
    batch_items = batch_response.json()["data"]
    assert len(batch_items) == 2
    assert batch_items[0]["deliveryType"] == "FILE"
    assert batch_items[1]["deliveryType"] == "NETDISK"
    assert batch_items[1]["netdiskUrl"] == "https://pan.example.com/s/txyl"

    update_payload = {
        "title": "Step 8 更新后资料",
        "description": "更新成网盘版本",
        "price": 100,
        "school": "电子科技大学",
        "college": "信通",
        "major": "通信",
        "gradeType": "STAGE",
        "gradeValue": "大四",
        "generalCourse": False,
        "courseCategory": "MAJOR",
        "tags": "期末速成",
        "deliveryMethod": "NETDISK",
        "netdiskUrl": "https://pan.example.com/s/updated",
        "netdiskPassword": "5678",
        "previewWatermarkEnabled": True,
        "previewSource": "AUTO",
        "customPreviewText": None,
        "customPreviewClear": True,
        "copyrightOwner": "Alice",
    }
    update_response = client.put(
        f"/api/materials/{material_id}",
        headers=alice_headers,
        files=[("payload", _payload_part(update_payload))],
    )
    assert update_response.status_code == 200
    updated = update_response.json()["data"]
    assert updated["title"] == "Step 8 更新后资料"
    assert updated["hasFile"] is False
    assert updated["hasNetdisk"] is True
    assert updated["netdiskUrl"] == "https://pan.example.com/s/updated"
    assert updated["customPreviewImages"] == []

    delete_response = client.delete(f"/api/materials/{material_id}", headers=alice_headers)
    assert delete_response.status_code == 200
    assert client.get(f"/api/materials/{material_id}").status_code == 404


def test_step8_download_permissions_and_quota_boundaries_match_current_rules(
    client: TestClient,
    auth_service: AuthService,
) -> None:
    seed_read_users(auth_service, with_follow_graph=True)

    with session_scope() as session:
        user = auth_service.repo.find_user_by_id(session, 1)
        assert user is not None
        user.free_download_quota = 0

    alice_headers = build_auth_headers(1, 1)
    baishan_headers = build_auth_headers(2, 2)

    quota_response = client.get("/api/materials/101/download", headers=alice_headers)
    assert quota_response.status_code == 403
    assert quota_response.json()["error"]["code"] == "DOWNLOAD_QUOTA_EXHAUSTED"

    paid_response = client.get("/api/materials/104/download", headers=baishan_headers)
    assert paid_response.status_code == 403
    assert paid_response.json()["msg"] == "请先购买后再下载"


def test_batch_download_does_not_overdraw_free_quota(
    client: TestClient,
    auth_service: AuthService,
) -> None:
    seed_read_users(auth_service, with_follow_graph=True)

    with session_scope() as session:
        user = auth_service.repo.find_user_by_id(session, 1)
        assert user is not None
        user.free_download_quota = 1

    alice_headers = build_auth_headers(1, 1)
    response = client.post("/api/materials/downloads/batch", json={"materialIds": [101, 103]}, headers=alice_headers)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "DOWNLOAD_QUOTA_EXHAUSTED"
    with session_scope() as session:
        user = session.get(AuthUser, 1)
        assert user is not None
        assert user.free_download_quota == 1
