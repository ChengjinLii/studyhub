from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_payment_service
from app.core.db import session_scope
from app.providers.payment import PaymentNotification
from app.services.auth_service import AuthService
from tests.support import build_auth_headers, seed_read_users
from tests.test_step11_payment_payout_worker import _create_alipay_order, _create_paid_material


class _ForceCheckStub:
    def __init__(self, delegate: Any, result: PaymentNotification | None) -> None:
        self._delegate = delegate
        self.result = result
        self.provider_name = delegate.provider_name
        self.channel_name = delegate.channel_name

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)

    def build_force_check_notification(self, *, out_trade_no: str, order: Any) -> PaymentNotification | None:
        return self.result


def _load_order(out_trade_no: str):
    service = get_payment_service()
    with session_scope() as session:
        order = service.finance_repo.find_order_by_out_trade_no(session, out_trade_no)
        assert order is not None
        session.expunge(order)
        return order


def _set_material_price(material_id: int, price_cents: int) -> None:
    service = get_payment_service()
    with session_scope() as session:
        material = service.material_repo.get_material(session, material_id)
        assert material is not None
        material.price = price_cents
        service.material_repo.save_material(session, material)
        session.commit()


def test_existing_purchase_record_never_creates_a_payable_order(client: TestClient, auth_service: AuthService) -> None:
    seed_read_users(auth_service, with_follow_graph=True)
    alice_headers = build_auth_headers(1, 1)
    baishan_headers = build_auth_headers(2, 2)
    material_id = _create_paid_material(client, baishan_headers, title="已拥有记录不可生成应付订单", price_cents=10000)
    service = get_payment_service()
    with session_scope() as session:
        # e.g. a free-download purchase recorded while the material was still free
        service.material_repo.add_purchase(session, material_id=material_id, user_id=1, source="free-download")
        session.commit()

    response = client.post("/api/orders", headers=alice_headers, json={"materialId": material_id, "channel": "alipay_page"})

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "PAID"
    assert data["amount"] == 0
    order = _load_order(str(data["orderNo"]))
    assert int(order.amount or 0) == 0
    assert int(order.creator_payable_amount or 0) == 0
    assert int(order.platform_fee_amount or 0) == 0


def test_force_check_does_not_mark_paid_when_gateway_amount_differs(
    client: TestClient,
    auth_service: AuthService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_read_users(auth_service, with_follow_graph=True)
    alice_headers = build_auth_headers(1, 1)
    baishan_headers = build_auth_headers(2, 2)
    material_id = _create_paid_material(client, baishan_headers, title="查单金额校验", price_cents=5000)
    out_trade_no, _ = _create_alipay_order(client, alice_headers, material_id)
    service = get_payment_service()
    stub = _ForceCheckStub(service.payment_provider, PaymentNotification(out_trade_no=out_trade_no, trade_no="ALI-1-CENT", amount_cents=1))
    monkeypatch.setattr(service, "payment_provider", stub)

    response = client.get("/api/orders/status", params={"orderNo": out_trade_no, "force": 1}, headers=alice_headers)

    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "CREATED"
    assert _load_order(out_trade_no).status == "CREATED"

    stub.result = PaymentNotification(out_trade_no=out_trade_no, trade_no="ALI-FULL", amount_cents=5000)
    response = client.get("/api/orders/status", params={"orderNo": out_trade_no, "force": 1}, headers=alice_headers)
    assert response.json()["data"]["status"] == "PAID"


def test_repricing_never_changes_amount_behind_an_issued_trade_number(client: TestClient, auth_service: AuthService) -> None:
    seed_read_users(auth_service, with_follow_graph=True)
    alice_headers = build_auth_headers(1, 1)
    baishan_headers = build_auth_headers(2, 2)
    material_id = _create_paid_material(client, baishan_headers, title="改价不得复用交易号", price_cents=1)
    first_trade_no, _ = _create_alipay_order(client, alice_headers, material_id)

    _set_material_price(material_id, 50000)
    response = client.post("/api/orders", headers=alice_headers, json={"materialId": material_id, "channel": "alipay_page"})
    assert response.status_code == 200, response.text

    # The checkout already issued for the 1-cent price keeps its amount; the new price gets a new trade number.
    assert int(_load_order(first_trade_no).amount or 0) == 1
    second_trade_no, _ = _create_alipay_order(client, alice_headers, material_id)
    assert second_trade_no != first_trade_no
    assert int(_load_order(second_trade_no).amount or 0) == 50000
