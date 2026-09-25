from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_requests_service
from app.core.config import get_settings
from app.core.db import session_scope
from app.providers.payment import PaymentNotification
from app.services.auth_service import AuthService
from tests.support import build_auth_headers, seed_read_users


GATEWAY_FORM = '<form id="studyhub-alipay-form" method="GET" action="https://openapi.alipay.com/gateway.do"></form>'


class _GatewayStub:
    """Stands in for the real Alipay page provider: nothing is paid until the gateway says so."""

    provider_name = "alipay_page"
    channel_name = "alipay_page"

    def __init__(self) -> None:
        self.checkouts: list[dict[str, Any]] = []
        self.force_result: PaymentNotification | None = None

    def build_checkout_payload(self, *, out_trade_no: str, order: Any) -> dict[str, Any]:
        self.checkouts.append({"out_trade_no": out_trade_no, "amount": int(order.amount), "title": order.material_title})
        return {"status": "CREATED", "orderNo": out_trade_no, "form": GATEWAY_FORM}

    def build_force_check_notification(self, *, out_trade_no: str, order: Any) -> PaymentNotification | None:
        return self.force_result


def _create_paid_request(client: TestClient, headers: dict[str, str], *, budget: int = 2000) -> dict[str, Any]:
    response = client.post(
        "/api/requests",
        headers=headers,
        json={"course": "资金完整性回归求购", "keyword": "需要真题", "budget": budget, "urgencyTier": "WEEK"},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _contribution_status(client: TestClient, headers: dict[str, str], order_no: str, *, force: bool) -> str:
    params: dict[str, object] = {"orderNo": order_no}
    if force:
        params["force"] = 1
    response = client.get("/api/requests/contributions/status", params=params, headers=headers)
    assert response.status_code == 200, response.text
    return str(response.json()["data"]["status"])


def _notify_paid(client: TestClient, out_trade_no: str, *, total_amount: str) -> None:
    response = client.post(
        "/api/pay/alipay/notify",
        data={
            "out_trade_no": out_trade_no,
            "trade_no": f"ALI-{out_trade_no[-8:]}",
            "trade_status": "TRADE_SUCCESS",
            "total_amount": total_amount,
        },
    )
    assert response.status_code == 200, response.text
    assert response.text == "success"


def _load_request(request_id: int):
    service = get_requests_service()
    with session_scope() as session:
        request = service.request_repo.get_request(session, request_id)
        assert request is not None
        session.expunge(request)
        return request


def _load_contribution(out_trade_no: str):
    service = get_requests_service()
    with session_scope() as session:
        contribution = service.request_repo.find_contribution_by_out_trade_no(session, out_trade_no)
        assert contribution is not None
        session.expunge(contribution)
        return contribution


def test_request_checkout_goes_through_payment_gateway(
    client: TestClient,
    auth_service: AuthService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_read_users(auth_service, with_follow_graph=True)
    gateway = _GatewayStub()
    monkeypatch.setattr(get_requests_service(), "payment_provider", gateway)

    created = _create_paid_request(client, build_auth_headers(1, 1), budget=2000)

    assert created["paymentRequired"] is True
    assert created["form"] == GATEWAY_FORM
    assert gateway.checkouts == [
        {"out_trade_no": created["outTradeNo"], "amount": 2000, "title": gateway.checkouts[0]["title"]}
    ]
    assert gateway.checkouts[0]["title"]


def test_request_force_check_only_marks_paid_after_gateway_confirms_amount(
    client: TestClient,
    auth_service: AuthService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_read_users(auth_service, with_follow_graph=True)
    alice_headers = build_auth_headers(1, 1)
    gateway = _GatewayStub()
    monkeypatch.setattr(get_requests_service(), "payment_provider", gateway)
    created = _create_paid_request(client, alice_headers, budget=2000)
    order_no = created["outTradeNo"]
    request_id = int(created["request"]["id"])

    # Gateway has no successful trade: forcing must not fabricate a payment.
    assert _contribution_status(client, alice_headers, order_no, force=True) == "CREATED"
    assert int(_load_request(request_id).funded_amount_cents or 0) == 0

    # Gateway reports a trade for a different amount: still not paid.
    gateway.force_result = PaymentNotification(out_trade_no=order_no, trade_no="ALI-WRONG", amount_cents=1)
    assert _contribution_status(client, alice_headers, order_no, force=True) == "CREATED"
    assert int(_load_request(request_id).funded_amount_cents or 0) == 0

    gateway.force_result = PaymentNotification(out_trade_no=order_no, trade_no="ALI-REAL-TRADE", amount_cents=2000)
    assert _contribution_status(client, alice_headers, order_no, force=True) == "PAID"
    contribution = _load_contribution(order_no)
    assert contribution.trade_no == "ALI-REAL-TRADE"
    assert int(_load_request(request_id).funded_amount_cents or 0) == 2000


def test_late_payment_notification_does_not_revive_refunded_contribution(
    client: TestClient,
    auth_service: AuthService,
) -> None:
    seed_read_users(auth_service, with_follow_graph=True)
    alice_headers = build_auth_headers(1, 1)
    baishan_headers = build_auth_headers(2, 2)
    created = _create_paid_request(client, alice_headers, budget=2000)
    request_id = int(created["request"]["id"])
    _notify_paid(client, created["outTradeNo"], total_amount="20.00")

    follow = client.post(f"/api/requests/{request_id}/follow", headers=baishan_headers, json={"amount": 1500, "deadlineTier": "WEEK"})
    assert follow.status_code == 200, follow.text
    follower_order_no = follow.json()["data"]["outTradeNo"]
    _notify_paid(client, follower_order_no, total_amount="15.00")
    contribution_id = int(_load_contribution(follower_order_no).id)

    cancel = client.post(f"/api/requests/contributions/{contribution_id}/cancel", headers=baishan_headers)
    assert cancel.status_code == 200, cancel.text
    assert cancel.json()["data"]["status"] == "REFUNDED"
    assert int(_load_request(request_id).funded_amount_cents or 0) == 2000

    # Alipay retries the original notification after the refund went through.
    _notify_paid(client, follower_order_no, total_amount="15.00")

    assert _load_contribution(follower_order_no).status == "REFUNDED"
    request = _load_request(request_id)
    assert int(request.funded_amount_cents or 0) == 2000
    assert int(request.contribution_count or 0) == 1


def test_queued_follower_refund_releases_funds_immediately_and_keeps_request_open(
    client: TestClient,
    auth_service: AuthService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_read_users(auth_service, with_follow_graph=True)
    alice_headers = build_auth_headers(1, 1)
    baishan_headers = build_auth_headers(2, 2)
    created = _create_paid_request(client, alice_headers, budget=2000)
    request_id = int(created["request"]["id"])
    _notify_paid(client, created["outTradeNo"], total_amount="20.00")
    follow = client.post(f"/api/requests/{request_id}/follow", headers=baishan_headers, json={"amount": 1500, "deadlineTier": "WEEK"})
    assert follow.status_code == 200, follow.text
    follower_order_no = follow.json()["data"]["outTradeNo"]
    _notify_paid(client, follower_order_no, total_amount="15.00")
    assert int(_load_request(request_id).funded_amount_cents or 0) == 3500
    contribution_id = int(_load_contribution(follower_order_no).id)

    monkeypatch.setattr(get_settings(), "finance_outbox_enabled", True)
    cancel = client.post(f"/api/requests/contributions/{contribution_id}/cancel", headers=baishan_headers)
    assert cancel.status_code == 200, cancel.text
    assert cancel.json()["data"]["status"] == "REFUNDING"

    # The refund is only queued, but the money must already be out of the request's pool so
    # an acceptance before the worker runs cannot settle it to the responder as well.
    request = _load_request(request_id)
    assert request.status == "OPEN"
    assert int(request.funded_amount_cents or 0) == 2000

    service = get_requests_service()
    with session_scope() as session:
        assert service.process_refund_instructions(session) == 1

    assert _load_contribution(follower_order_no).status == "REFUNDED"
    request = _load_request(request_id)
    assert request.status == "OPEN"
    assert int(request.funded_amount_cents or 0) == 2000
    assert int(request.contribution_count or 0) == 1
