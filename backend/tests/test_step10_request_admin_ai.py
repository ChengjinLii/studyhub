from __future__ import annotations

import base64
from io import BytesIO
import json
import zipfile

from fastapi.testclient import TestClient

from app.api.deps import get_finance_repo
from app.core.db import session_scope
from app.services.auth_service import AuthService
from tests.support import build_auth_headers, seed_read_users


PNG_1X1 = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4//8/AwAI/AL+p5qgoAAAAABJRU5ErkJggg==")


def _zip_bytes(name: str, content: str) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, content)
    return buffer.getvalue()


def _payload_part(payload: dict[str, object]) -> tuple[str, str, str]:
    return ("payload.json", json.dumps(payload, ensure_ascii=False), "application/json")


def _extract_json_block(raw: str) -> dict[str, object]:
    start = raw.index("<json>") + 6 if "<json>" in raw else 0
    end = raw.index("</json>") if "</json>" in raw else len(raw)
    return json.loads(raw[start:end])


def test_step10_request_flow_covers_create_follow_deadline_cancel_upload_preview_accept(
    client: TestClient,
    auth_service: AuthService,
) -> None:
    seed_read_users(auth_service, with_follow_graph=True)
    alice_headers = build_auth_headers(1, 1)
    baishan_headers = build_auth_headers(2, 2)

    create_response = client.post(
        "/api/requests",
        headers=alice_headers,
        json={
            "course": "Step 10 概率论真题",
            "keyword": "需要近三年期末真题和解析",
            "budget": 2000,
            "urgencyTier": "WEEK",
            "creatorFloor": 500,
            "previewRequirement": "至少展示前 2 页",
            "school": "电子科技大学",
            "college": "计算机科学与工程学院",
            "major": "软件工程",
        },
    )
    assert create_response.status_code == 200
    create_data = create_response.json()["data"]
    request_id = create_data["request"]["id"]
    owner_order_no = create_data["outTradeNo"]
    assert create_data["paymentRequired"] is True
    assert "/pay/result" in create_data["form"]

    owner_status_before_force = client.get(
        "/api/requests/contributions/status",
        params={"orderNo": owner_order_no},
        headers=alice_headers,
    )
    assert owner_status_before_force.status_code == 200
    assert owner_status_before_force.json()["data"]["status"] == "CREATED"

    owner_status_after_force = client.get(
        "/api/requests/contributions/status",
        params={"orderNo": owner_order_no, "force": 1},
        headers=alice_headers,
    )
    assert owner_status_after_force.status_code == 200
    assert owner_status_after_force.json()["data"]["status"] == "PAID"
    assert owner_status_after_force.json()["data"]["requestId"] == request_id

    follow_response = client.post(
        f"/api/requests/{request_id}/follow",
        headers=baishan_headers,
        json={"amount": 1500, "deadlineTier": "WEEK"},
    )
    assert follow_response.status_code == 200
    follow_data = follow_response.json()["data"]
    follower_order_no = follow_data["outTradeNo"]

    follower_status_after_force = client.get(
        "/api/requests/contributions/status",
        params={"orderNo": follower_order_no, "force": 1},
        headers=baishan_headers,
    )
    assert follower_status_after_force.status_code == 200
    follower_contribution_id = follower_status_after_force.json()["data"]["contributionId"]
    assert follower_status_after_force.json()["data"]["status"] == "PAID"

    extend_deadline = client.put(
        f"/api/requests/contributions/{follower_contribution_id}/deadline",
        headers=baishan_headers,
        json={"deadlineTier": "MONTH"},
    )
    assert extend_deadline.status_code == 200
    assert extend_deadline.json()["data"]["deadlineTier"] == "MONTH"

    cancel_contribution = client.post(
        f"/api/requests/contributions/{follower_contribution_id}/cancel",
        headers=baishan_headers,
    )
    assert cancel_contribution.status_code == 200
    assert cancel_contribution.json()["data"]["status"] == "REFUNDED"

    material_payload = {
        "title": "Step 10 求购应答资料",
        "description": "用于应答求购的资料",
        "price": 0,
        "school": "电子科技大学",
        "college": "计算机科学与工程学院",
        "major": "软件工程",
        "gradeType": "STAGE",
        "gradeValue": "大三",
        "generalCourse": False,
        "courseCategory": "MAJOR",
        "tags": "期末真题,Step10",
        "deliveryMethod": "FILE",
        "previewWatermarkEnabled": True,
        "previewSource": "MANUAL",
        "copyrightOwner": "白山",
        "requestId": request_id,
    }
    material_response = client.post(
        "/api/materials",
        headers=baishan_headers,
        files=[
            ("payload", _payload_part(material_payload)),
            ("zip", ("step10.zip", _zip_bytes("answer.txt", "step10"), "application/zip")),
            ("previews", ("preview-1.png", PNG_1X1, "image/png")),
            ("previews", ("preview-2.png", PNG_1X1, "image/png")),
        ],
    )
    assert material_response.status_code == 200
    material_id = material_response.json()["data"]["id"]

    responses_response = client.get(f"/api/requests/{request_id}/responses", headers=alice_headers)
    assert responses_response.status_code == 200
    responses = responses_response.json()["data"]
    assert len(responses) == 1
    response_id = responses[0]["id"]
    assert responses[0]["materialId"] == material_id

    preview_view_response = client.post(
        f"/api/requests/{request_id}/preview-view",
        headers=alice_headers,
        json={"responseId": response_id, "loadedCount": 2},
    )
    assert preview_view_response.status_code == 200

    accept_response = client.post(
        f"/api/requests/{request_id}/accept",
        headers=alice_headers,
        json={"responseId": response_id},
    )
    assert accept_response.status_code == 200
    accepted = accept_response.json()["data"]
    assert accepted["status"] == "ACCEPTED"
    assert accepted["acceptedResponseId"] == response_id
    with session_scope() as session:
        assert get_finance_repo().find_settlement_by_source(session, "REQUEST", request_id) is None

    confirm_response = client.post(
        f"/api/requests/{request_id}/confirm-acceptance",
        headers=alice_headers,
    )
    assert confirm_response.status_code == 200
    confirmed = confirm_response.json()["data"]
    assert confirmed["status"] == "FULFILLED"
    assert confirmed["acceptedResponseId"] == response_id
    with session_scope() as session:
        settlement = get_finance_repo().find_settlement_by_source(session, "REQUEST", request_id)
        assert settlement is not None
        assert settlement.gross_amount == 2000
        assert settlement.platform_fee == 100
        assert settlement.payout_amount == 1900

    contributions_response = client.get(f"/api/requests/{request_id}/contributions", headers=alice_headers)
    assert contributions_response.status_code == 200
    contributions = contributions_response.json()["data"]
    assert len(contributions) == 2
    assert contributions[0]["status"] == "REFUNDED"
    assert contributions[1]["status"] == "PAID"


def test_step10_arbitration_admin_materials_and_ai_flow(
    client: TestClient,
    auth_service: AuthService,
) -> None:
    seed_read_users(auth_service, with_follow_graph=True)
    alice_headers = build_auth_headers(1, 1)
    baishan_headers = build_auth_headers(2, 2)
    admin_headers = build_auth_headers(3, 8)
    with session_scope() as session:
        developer = auth_service.create_local_user(
            session,
            username="step10developer",
            password="secret123",
            email="step10developer@example.com",
            verified=True,
            nickname="Step10 Developer",
            role_mask=24,
        )
        developer_id = developer.id
    developer_headers = build_auth_headers(developer_id, 24)

    create_request = client.post(
        "/api/requests",
        headers=alice_headers,
        json={
            "course": "Step 10 仲裁测试",
            "keyword": "需要实验报告模板",
            "budget": 1000,
            "urgencyTier": "FLEX",
            "school": "电子科技大学",
        },
    )
    assert create_request.status_code == 200
    request_id = create_request.json()["data"]["request"]["id"]
    order_no = create_request.json()["data"]["outTradeNo"]
    mark_paid = client.get(
        "/api/requests/contributions/status",
        params={"orderNo": order_no, "force": 1},
        headers=alice_headers,
    )
    assert mark_paid.status_code == 200
    assert mark_paid.json()["data"]["status"] == "PAID"

    material_payload = {
        "title": "Step 10 仲裁资料",
        "description": "仲裁流转资料",
        "price": 0,
        "school": "电子科技大学",
        "college": "信通",
        "major": "通信",
        "gradeType": "STAGE",
        "gradeValue": "大三",
        "generalCourse": False,
        "courseCategory": "MAJOR",
        "tags": "Step10,模板",
        "deliveryMethod": "FILE",
        "previewWatermarkEnabled": True,
        "previewSource": "MANUAL",
        "copyrightOwner": "白山",
        "requestId": request_id,
    }
    created_material = client.post(
        "/api/materials",
        headers=baishan_headers,
        files=[
            ("payload", _payload_part(material_payload)),
            ("zip", ("step10-dispute.zip", _zip_bytes("template.txt", "step10 dispute"), "application/zip")),
            ("previews", ("preview-1.png", PNG_1X1, "image/png")),
            ("previews", ("preview-2.png", PNG_1X1, "image/png")),
        ],
    )
    assert created_material.status_code == 200
    material_id = created_material.json()["data"]["id"]

    responses = client.get(f"/api/requests/{request_id}/responses", headers=alice_headers)
    response_id = responses.json()["data"][0]["id"]
    preview_view = client.post(
        f"/api/requests/{request_id}/preview-view",
        headers=alice_headers,
        json={"responseId": response_id, "loadedCount": 2},
    )
    assert preview_view.status_code == 200

    dispute_response = client.post(
        f"/api/requests/{request_id}/dispute",
        headers=alice_headers,
        json={"responseId": response_id, "reason": "资料不符合描述，需要发起仲裁处理。"},
    )
    assert dispute_response.status_code == 200
    assert dispute_response.json()["data"]["status"] == "DISPUTED"

    arbitration_decision = client.post(
        "/api/requests/arbitrations/1/decision",
        headers=admin_headers,
        json={"decision": "REFUND", "adminNote": "同意退款"},
    )
    assert arbitration_decision.status_code == 200
    assert arbitration_decision.json()["data"]["status"] == "REFUNDED"

    contributions = client.get(f"/api/requests/{request_id}/contributions", headers=alice_headers)
    assert contributions.status_code == 200
    assert contributions.json()["data"][0]["status"] == "REFUNDED"

    users_response = client.get("/api/admin/users", headers=admin_headers)
    assert users_response.status_code == 200
    assert any(item["username"] == "alice" for item in users_response.json()["data"])

    create_developer_forbidden = client.post(
        "/api/admin/users",
        headers=admin_headers,
        json={"username": "blocked-admin", "password": "secret123", "nickname": "Blocked", "roleMask": 24},
    )
    assert create_developer_forbidden.status_code == 403

    create_admin_user = client.post(
        "/api/admin/users",
        headers=developer_headers,
        json={"username": "step10admin", "password": "secret123", "nickname": "Step10 Admin", "roleMask": 9},
    )
    assert create_admin_user.status_code == 200
    created_user_id = create_admin_user.json()["data"]["id"]

    patch_roles = client.patch(
        f"/api/admin/users?id={created_user_id}",
        headers=developer_headers,
        json={"roleMask": 25},
    )
    assert patch_roles.status_code == 200
    assert patch_roles.json()["data"]["roleMask"] == 25

    seed_notes = client.get("/api/admin/user-notes", params={"userId": 1}, headers=admin_headers)
    assert seed_notes.status_code == 200
    assert seed_notes.json()["data"][0]["message"].startswith("感谢持续分享资料")

    create_note = client.post(
        "/api/admin/user-notes",
        params={"userId": 1},
        headers=admin_headers,
        json={"message": "Step 10 追加备注"},
    )
    assert create_note.status_code == 200
    assert create_note.json()["data"]["message"] == "Step 10 追加备注"

    materials_list = client.get("/api/admin/materials", params={"page": 0, "size": 20}, headers=admin_headers)
    assert materials_list.status_code == 200
    assert any(item["id"] == material_id for item in materials_list.json()["data"]["items"])

    batch_update = client.post(
        "/api/admin/materials/batch-update",
        headers=admin_headers,
        json={"materialIds": [material_id], "courseCategory": "GENERAL", "tags": "管理员标签", "tagsMode": "replace"},
    )
    assert batch_update.status_code == 200
    assert batch_update.json()["data"]["updated"] == 1

    batch_delete = client.post(
        "/api/admin/materials/batch-delete",
        headers=admin_headers,
        json={"materialIds": [material_id]},
    )
    assert batch_delete.status_code == 200
    removed_list = client.get("/api/admin/materials", params={"page": 0, "size": 20, "status": "removed"}, headers=admin_headers)
    assert removed_list.status_code == 200
    assert any(item["id"] == material_id for item in removed_list.json()["data"]["items"])

    restore_item = client.post(f"/api/admin/materials/{material_id}/restore", headers=admin_headers)
    assert restore_item.status_code == 200

    ai_chat = client.post(
        "/api/ai/chat",
        headers=admin_headers,
        json={"messages": [{"role": "user", "content": "帮我总结一下 Step 10 现在做了什么？"}]},
    )
    assert ai_chat.status_code == 200
    assert "Step 10" in ai_chat.json()["data"]["content"]

    ai_recommend = client.post(
        "/api/ai/recommend",
        headers=admin_headers,
        json={"query": "期末真题"},
    )
    assert ai_recommend.status_code == 200
    parsed = _extract_json_block(ai_recommend.json()["data"]["output"])
    assert parsed["recommendations"]
    assert parsed["recommendations"][0]["material_id"] == 101
