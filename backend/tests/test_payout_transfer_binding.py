from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from io import BytesIO
import json
import zipfile

from fastapi.testclient import TestClient

from app.api.deps import get_finance_repo, get_worker_service
from app.core.db import session_scope
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


def _create_paid_material(client: TestClient, headers: dict[str, str], *, title: str, price_cents: int) -> int:
    payload = {
        "title": title,
        "description": "转账绑定回归测试资料",
        "price": price_cents,
        "school": "电子科技大学",
        "college": "计算机科学与工程学院",
        "major": "软件工程",
        "gradeType": "STAGE",
        "gradeValue": "大三",
        "generalCourse": False,
        "courseCategory": "MAJOR",
        "tags": "binding,付费资料",
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
            ("zip", ("binding.zip", _zip_bytes("readme.txt", "binding test"), "application/zip")),
            ("previews", ("preview-1.png", PNG_1X1, "image/png")),
        ],
    )
    assert response.status_code == 200, response.text
    return int(response.json()["data"]["id"])


def _pay_order(client: TestClient, headers: dict[str, str], material_id: int, *, total_amount: str) -> tuple[str, int]:
    create = client.post("/api/pay/alipay/create", headers=headers, json={"materialId": material_id})
    assert create.status_code == 200, create.text
    out_trade_no = str(create.json()["data"]["orderNo"])
    order_id = int(create.json()["data"]["orderId"])
    notify = client.post(
        "/api/pay/alipay/notify",
        data={
            "out_trade_no": out_trade_no,
            "trade_no": f"ALI-BIND-{order_id}",
            "trade_status": "TRADE_SUCCESS",
            "total_amount": total_amount,
        },
    )
    assert notify.status_code == 200, notify.text
    assert notify.text == "success"
    return out_trade_no, order_id


def _make_settlement_due(out_trade_no: str) -> None:
    """Backdate the paid order past the settlement delay, then run the settlement job."""
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


def _create_payout_application(client: TestClient, headers: dict[str, str]) -> int:
    response = client.post(
        "/api/creator-payout-applications",
        headers=headers,
        json={
            "alipayAccount": "chengjin@example.com",
            "alipayName": "白山",
            "realName": "白山",
            "idCardNo": "51010619990101123X",
            "contactType": "QQ",
            "contactValue": "2731938007",
            "notes": "binding regression",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["kycStatus"] == "VERIFIED"
    return int(response.json()["data"]["id"])


def _approve_application(client: TestClient, admin_headers: dict[str, str], application_id: int) -> None:
    review = client.patch(
        f"/api/admin/creator-payout-applications?id={application_id}",
        headers=admin_headers,
        json={"status": "APPROVED", "reviewNotes": "审核通过"},
    )
    assert review.status_code == 200, review.text
    assert review.json()["data"]["status"] == "APPROVED"


def _gateway_success(client: TestClient, out_biz_no: str) -> None:
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


def test_success_callback_settles_only_settlements_bound_at_approval(
    client: TestClient,
    auth_service: AuthService,
) -> None:
    """核心竞态回归：批准与 SUCCESS 回调之间新到期的结算单不得被标记 PAID。"""
    seed_read_users(auth_service, with_follow_graph=True)
    alice_headers = build_auth_headers(1, 1)
    baishan_headers = build_auth_headers(2, 2)
    admin_headers = build_auth_headers(3, 8)
    finance_repo = get_finance_repo()

    # S1: 2000 分订单 → 结算单 payout 1400，到期可提现
    material_1 = _create_paid_material(client, baishan_headers, title="绑定回归资料一", price_cents=2000)
    out_trade_no_1, order_id_1 = _pay_order(client, alice_headers, material_1, total_amount="20.00")
    _make_settlement_due(out_trade_no_1)

    application_id = _create_payout_application(client, baishan_headers)
    _approve_application(client, admin_headers, application_id)

    with session_scope() as session:
        transfer = finance_repo.find_transfer_by_application(session, application_id)
        assert transfer is not None
        assert transfer.status == "SUBMITTED"
        assert int(transfer.amount) == 1400
        transfer_id = int(transfer.id)
        out_biz_no = transfer.out_biz_no
        settlements = finance_repo.list_settlements_for_uploader(session, 2)
        s1 = next(item for item in settlements if item.order_id == order_id_1)
        assert s1.payout_transfer_id == transfer_id  # 批准时即绑定

    # S2: 转账在途期间新到期的结算单（批准之后、SUCCESS 回调之前）
    material_2 = _create_paid_material(client, baishan_headers, title="绑定回归资料二", price_cents=1000)
    out_trade_no_2, order_id_2 = _pay_order(client, alice_headers, material_2, total_amount="10.00")
    _make_settlement_due(out_trade_no_2)

    _gateway_success(client, out_biz_no)

    with session_scope() as session:
        settlements = finance_repo.list_settlements_for_uploader(session, 2)
        s1 = next(item for item in settlements if item.order_id == order_id_1)
        s2 = next(item for item in settlements if item.order_id == order_id_2)
        assert s1.status == "PAID"
        assert s1.payout_transfer_id == transfer_id
        # 关键断言：S2 未参与本次转账金额，不得被结算，且保持可认领
        assert s2.status == "PENDING"
        assert s2.payout_transfer_id is None

    latest = client.get("/api/creator-payout-applications/me", headers=baishan_headers)
    assert latest.status_code == 200
    assert latest.json()["data"]["status"] == "SETTLED"


def test_in_flight_settlements_excluded_from_withdrawable_earnings(
    client: TestClient,
    auth_service: AuthService,
) -> None:
    """在途排除：已绑定转账的结算单不再计入可提现金额，但仍计入未结总额。"""
    seed_read_users(auth_service, with_follow_graph=True)
    alice_headers = build_auth_headers(1, 1)
    baishan_headers = build_auth_headers(2, 2)
    admin_headers = build_auth_headers(3, 8)

    material_id = _create_paid_material(client, baishan_headers, title="在途排除资料", price_cents=2000)
    out_trade_no, _ = _pay_order(client, alice_headers, material_id, total_amount="20.00")
    _make_settlement_due(out_trade_no)

    application_id = _create_payout_application(client, baishan_headers)
    before = client.get("/api/creator-payout-applications/me", headers=baishan_headers)
    assert before.json()["data"]["earnings"]["payoutAmount"] == 1400

    _approve_application(client, admin_headers, application_id)

    after = client.get("/api/creator-payout-applications/me", headers=baishan_headers)
    earnings = after.json()["data"]["earnings"]
    assert earnings["payoutAmount"] == 0  # S1 在途，不可重复提现
    assert earnings["unclaimedPayoutTotal"] == 1400  # 仍是 PENDING，未结总额口径不变


def test_legacy_unbound_transfer_falls_back_and_repeat_callback_is_idempotent(
    client: TestClient,
    auth_service: AuthService,
) -> None:
    """遗留兼容：部署前已提交、无绑定结算单的在途转账，SUCCESS 时按旧口径认领；重复回调幂等。"""
    seed_read_users(auth_service, with_follow_graph=True)
    alice_headers = build_auth_headers(1, 1)
    baishan_headers = build_auth_headers(2, 2)
    finance_repo = get_finance_repo()

    material_1 = _create_paid_material(client, baishan_headers, title="遗留回退资料一", price_cents=2000)
    out_trade_no_1, order_id_1 = _pay_order(client, alice_headers, material_1, total_amount="20.00")
    _make_settlement_due(out_trade_no_1)

    application_id = _create_payout_application(client, baishan_headers)

    # 直接落库一笔"部署前"的在途转账：SUBMITTED 且没有任何绑定结算单
    from app.models.finance import PayoutTransferRecord

    with session_scope() as session:
        legacy = PayoutTransferRecord(
            payout_application_id=application_id,
            uploader_id=2,
            out_biz_no=finance_repo.build_out_biz_no(),
            amount=1400,
            payee_account="chengjin@example.com",
            payee_name="白山",
            status="SUBMITTED",
        )
        legacy = finance_repo.save_payout_transfer(session, legacy)
        legacy_id = int(legacy.id)
        out_biz_no = legacy.out_biz_no
        session.commit()

    _gateway_success(client, out_biz_no)

    with session_scope() as session:
        settlements = finance_repo.list_settlements_for_uploader(session, 2)
        s1 = next(item for item in settlements if item.order_id == order_id_1)
        assert s1.status == "PAID"  # 回退口径认领并结算
        assert s1.payout_transfer_id == legacy_id  # 盖章，防重复

    # 在途期间又有新结算单到期，然后重复投递 SUCCESS 回调
    material_2 = _create_paid_material(client, baishan_headers, title="遗留回退资料二", price_cents=1000)
    out_trade_no_2, order_id_2 = _pay_order(client, alice_headers, material_2, total_amount="10.00")
    _make_settlement_due(out_trade_no_2)

    _gateway_success(client, out_biz_no)

    with session_scope() as session:
        settlements = finance_repo.list_settlements_for_uploader(session, 2)
        s2 = next(item for item in settlements if item.order_id == order_id_2)
        # 幂等关键断言：已盖章的转账重复回调不得再认领新结算单
        assert s2.status == "PENDING"
        assert s2.payout_transfer_id is None
