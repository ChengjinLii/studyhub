from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from io import BytesIO
import json
import zipfile

from fastapi.testclient import TestClient

from app.api.deps import get_finance_repo, get_worker_service
from app.core.db import session_scope
from app.repos.request_repo import RequestRepository
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


def _create_paid_material(client: TestClient, headers: dict[str, str], *, title: str, price_cents: int = 1200) -> int:
    payload = {
        "title": title,
        "description": "Step 11 付费资料",
        "price": price_cents,
        "school": "电子科技大学",
        "college": "计算机科学与工程学院",
        "major": "软件工程",
        "gradeType": "STAGE",
        "gradeValue": "大三",
        "generalCourse": False,
        "courseCategory": "MAJOR",
        "tags": "Step11,付费资料",
        "deliveryMethod": "FILE",
        "previewWatermarkEnabled": True,
        "previewSource": "MANUAL",
        "copyrightOwner": "白山",
    }
    response = client.post(
        "/api/materials",
        headers=headers,
        files=[
            ("payload", _payload_part(payload)),
            ("zip", ("step11.zip", _zip_bytes("readme.txt", "step11 payment"), "application/zip")),
            ("previews", ("preview-1.png", PNG_1X1, "image/png")),
            ("previews", ("preview-2.png", PNG_1X1, "image/png")),
        ],
    )
    assert response.status_code == 200, response.text
    return int(response.json()["data"]["id"])


def _create_alipay_order(client: TestClient, headers: dict[str, str], material_id: int) -> tuple[str, int]:
    response = client.post("/api/pay/alipay/create", headers=headers, json={"materialId": material_id})
    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    return str(payload["orderNo"]), int(payload["orderId"])


def _notify_order_paid(client: TestClient, out_trade_no: str, *, total_amount: str) -> None:
    response = client.post(
        "/api/pay/alipay/notify",
        data={
            "out_trade_no": out_trade_no,
            "trade_no": "ALI-STEP11-001",
            "trade_status": "TRADE_SUCCESS",
            "total_amount": total_amount,
        },
    )
    assert response.status_code == 200, response.text
    assert response.text == "success"
    assert response.headers["content-type"].startswith("text/plain")


def test_step11_payment_query_download_and_creator_metrics(client: TestClient, auth_service: AuthService) -> None:
    seed_read_users(auth_service, with_follow_graph=True)
    alice_headers = build_auth_headers(1, 1)
    baishan_headers = build_auth_headers(2, 2)
    admin_headers = build_auth_headers(3, 8)

    material_id = _create_paid_material(client, baishan_headers, title="Step 11 支付链路")
    out_trade_no, _order_id = _create_alipay_order(client, alice_headers, material_id)

    status_before = client.get("/api/pay/orders/status", params={"orderNo": out_trade_no}, headers=alice_headers)
    assert status_before.status_code == 200
    assert status_before.json()["data"]["status"] == "CREATED"

    _notify_order_paid(client, out_trade_no, total_amount="12.00")

    status_after = client.get("/api/pay/orders/status", params={"orderNo": out_trade_no}, headers=alice_headers)
    assert status_after.status_code == 200
    status_payload = status_after.json()["data"]
    assert status_payload["status"] == "PAID"
    assert status_payload["materialId"] == material_id

    query_response = client.get("/api/pay/alipay/query", params={"out_trade_no": out_trade_no}, headers=admin_headers)
    assert query_response.status_code == 200
    query_payload = query_response.json()["data"]
    assert query_payload["status"] == "PAID"
    assert query_payload["materialId"] == material_id

    download_response = client.get(f"/api/materials/{material_id}/download", headers=alice_headers)
    assert download_response.status_code == 200, download_response.text
    assert download_response.json()["data"]["url"]

    metrics_response = client.get("/api/creator/metrics", headers=baishan_headers)
    assert metrics_response.status_code == 200
    metrics = metrics_response.json()["data"]
    assert metrics["weekSales"] >= 1
    assert metrics["weekGross"] >= 12.0
    assert metrics["weekNet"] >= 8.4


def test_step11_payout_schedule_qr_application_gateway_and_monthly_overview(
    client: TestClient,
    auth_service: AuthService,
) -> None:
    seed_read_users(auth_service, with_follow_graph=True)
    alice_headers = build_auth_headers(1, 1)
    baishan_headers = build_auth_headers(2, 2)
    admin_headers = build_auth_headers(3, 8)

    material_id = _create_paid_material(client, baishan_headers, title="Step 11 提现链路", price_cents=2000)
    out_trade_no, _ = _create_alipay_order(client, alice_headers, material_id)
    _notify_order_paid(client, out_trade_no, total_amount="20.00")

    schedule_update = client.patch(
        "/api/admin/payout-schedule",
        headers=admin_headers,
        json={"launchDate": "2026-03-01", "nextPayoutDate": "2026-03-29"},
    )
    assert schedule_update.status_code == 200, schedule_update.text

    finance_repo = get_finance_repo()
    paid_at = datetime.now(UTC) - timedelta(days=8)
    with session_scope() as session:
        order = finance_repo.find_order_by_out_trade_no(session, out_trade_no)
        assert order is not None
        order.paid_at = paid_at
        order.created_at = paid_at
        finance_repo.save_order(session, order)
        session.commit()

    worker_service = get_worker_service()
    with session_scope() as session:
        result = worker_service.run_settlement_job(session)
    assert result["acquired"] is True
    assert result["generated"] >= 1

    upload_qr = client.post(
        "/api/me/payout-qr",
        headers=baishan_headers,
        files={"file": ("payout-qr.png", PNG_1X1, "image/png")},
    )
    assert upload_qr.status_code == 200, upload_qr.text
    payout_qr_url = upload_qr.json()["data"]["payoutQrUrl"]
    assert payout_qr_url

    qr_image = client.get(payout_qr_url, headers=baishan_headers)
    assert qr_image.status_code == 200
    assert qr_image.headers["content-type"].startswith("image/")

    create_application = client.post(
        "/api/creator-payout-applications",
        headers=baishan_headers,
        json={
            "alipayAccount": "chengjin@example.com",
            "alipayName": "白山",
            "realName": "白山",
            "idCardNo": "51010619990101123X",
            "contactType": "QQ",
            "contactValue": "2731938007",
            "notes": "Step 11 payout application",
        },
    )
    assert create_application.status_code == 200, create_application.text
    application_payload = create_application.json()["data"]
    assert application_payload["status"] == "PENDING"
    assert application_payload["kycStatus"] == "VERIFIED"
    assert application_payload["earnings"]["payoutAmount"] == 1400
    application_id = int(application_payload["id"])

    admin_list = client.get("/api/admin/creator-payout-applications", headers=admin_headers)
    assert admin_list.status_code == 200
    assert any(int(item["id"]) == application_id for item in admin_list.json()["data"]["items"])

    details = client.get(f"/api/admin/creator-payout-applications/{application_id}/details", headers=admin_headers)
    assert details.status_code == 200
    detail_items = details.json()["data"]
    assert len(detail_items) >= 1

    review = client.patch(
        f"/api/admin/creator-payout-applications?id={application_id}",
        headers=admin_headers,
        json={"status": "APPROVED", "reviewNotes": "审核通过"},
    )
    assert review.status_code == 200, review.text
    assert review.json()["data"]["status"] == "APPROVED"

    with session_scope() as session:
        transfer = finance_repo.find_transfer_by_application(session, application_id)
        assert transfer is not None
        out_biz_no = transfer.out_biz_no

    gateway = client.post(
        "/api/pay/alipay/gateway",
        data={
            "biz_type": "alipay.fund.trans.order.changed",
            "out_biz_no": out_biz_no,
            "status": "SUCCESS",
        },
    )
    assert gateway.status_code == 200
    assert gateway.text == "success"
    assert gateway.headers["content-type"].startswith("text/plain")

    latest_application = client.get("/api/creator-payout-applications/me", headers=baishan_headers)
    assert latest_application.status_code == 200
    assert latest_application.json()["data"]["status"] == "SETTLED"

    month_key = paid_at.strftime("%Y-%m")
    monthly_overview = client.get("/api/admin/monthly-payout-overview", params={"month": month_key}, headers=admin_headers)
    assert monthly_overview.status_code == 200
    monthly_payload = monthly_overview.json()["data"]
    assert monthly_payload["creatorCount"] >= 1
    first_item = next(item for item in monthly_payload["items"] if int(item["uploaderId"]) == 2)
    assert first_item["hasPayoutQr"] is True
    assert first_item["payoutAmount"] == 1400

    admin_qr = client.get("/api/admin/monthly-payout-overview/users/2/payout-qr", headers=admin_headers)
    assert admin_qr.status_code == 200
    assert admin_qr.json()["data"]["hasPayoutQr"] is True
    assert admin_qr.json()["data"]["payoutQrUrl"]

    marked = client.patch(
        "/api/admin/monthly-payout-overview/marks",
        headers=admin_headers,
        json={"monthKey": month_key, "uploaderId": 2, "markPaid": True},
    )
    assert marked.status_code == 200
    assert marked.json()["data"]["markedPaid"] is True


def test_step11_request_refund_worker_and_lock_semantics(client: TestClient, auth_service: AuthService) -> None:
    seed_read_users(auth_service, with_follow_graph=True)
    alice_headers = build_auth_headers(1, 1)
    request_repo = RequestRepository()
    worker_service = get_worker_service()

    create_request = client.post(
        "/api/requests",
        headers=alice_headers,
        json={
            "course": "Step 11 求购退款任务",
            "keyword": "需要自动退款验证",
            "budget": 1000,
            "urgencyTier": "FLEX",
            "school": "电子科技大学",
        },
    )
    assert create_request.status_code == 200, create_request.text
    request_payload = create_request.json()["data"]
    request_id = int(request_payload["request"]["id"])
    contribution_order_no = str(request_payload["outTradeNo"])

    notify_request = client.post(
        "/api/pay/alipay/notify",
        data={
            "out_trade_no": contribution_order_no,
            "trade_no": "ALI-RQ-001",
            "trade_status": "TRADE_SUCCESS",
            "total_amount": "10.00",
        },
    )
    assert notify_request.status_code == 200
    assert notify_request.text == "success"

    with session_scope() as session:
        request = request_repo.get_request(session, request_id)
        assert request is not None
        request.created_at = datetime.now(UTC) - timedelta(hours=49)
        request.updated_at = request.created_at
        request_repo.save_request(session, request)
        session.commit()

    with session_scope() as session:
        assert worker_service.try_acquire_lock(
            session,
            lock_name="studyhub:request-refund",
            owner_token="worker-a",
            ttl_seconds=120,
        ) is True
    with session_scope() as session:
        assert worker_service.try_acquire_lock(
            session,
            lock_name="studyhub:request-refund",
            owner_token="worker-b",
            ttl_seconds=120,
        ) is False
    with session_scope() as session:
        worker_service.release_lock(session, lock_name="studyhub:request-refund", owner_token="worker-a")

    with session_scope() as session:
        result = worker_service.run_request_refund_job(session)
    assert result["acquired"] is True
    assert result["processed"] >= 1

    detail = client.get(f"/api/requests/{request_id}", headers=alice_headers)
    assert detail.status_code == 200
    assert detail.json()["data"]["status"] == "REFUNDED"
