from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_finance_repo, get_payout_service
from app.core.db import session_scope
from app.providers.transfer import TransferResult
from app.services.auth_service import AuthService
from tests.support import build_auth_headers, seed_read_users
from tests.test_payout_transfer_binding import (
    _approve_application,
    _create_paid_material,
    _create_payout_application,
    _gateway_status,
    _gateway_success,
    _make_settlement_due,
    _pay_order,
)


class _TransferGatewayStub:
    provider_name = "alipay_transfer"

    def __init__(self, delegate: Any, *, query_results: dict[str, Any]) -> None:
        self._delegate = delegate
        self.query_results = query_results
        self.submitted: list[str] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)

    def query_transfer(self, transfer: Any) -> TransferResult:
        outcome = self.query_results[transfer.out_biz_no]
        if isinstance(outcome, Exception):
            raise outcome
        return TransferResult(status=outcome, provider_name=self.provider_name)

    def submit_transfer(self, transfer: Any) -> TransferResult:
        self.submitted.append(transfer.out_biz_no)
        return TransferResult(status="SUBMITTED", provider_name=self.provider_name)


def _approved_transfer(client: TestClient, *, uploader_headers: dict[str, str], title: str) -> tuple[int, str]:
    alice_headers = build_auth_headers(1, 1)
    admin_headers = build_auth_headers(3, 8)
    material_id = _create_paid_material(client, uploader_headers, title=title, price_cents=2000)
    out_trade_no, _ = _pay_order(client, alice_headers, material_id, total_amount="20.00")
    _make_settlement_due(out_trade_no)
    application_id = _create_payout_application(client, uploader_headers)
    _approve_application(client, admin_headers, application_id)
    with session_scope() as session:
        transfer = get_finance_repo().find_transfer_by_application(session, application_id)
        assert transfer is not None
        return int(transfer.id), transfer.out_biz_no


def _set_transfer_status(transfer_id: int, status_value: str) -> None:
    finance_repo = get_finance_repo()
    with session_scope() as session:
        transfer = finance_repo.get_payout_transfer(session, transfer_id)
        assert transfer is not None
        transfer.status = status_value
        finance_repo.save_payout_transfer(session, transfer)
        session.commit()


def test_pending_transfer_unknown_to_alipay_is_resubmitted_with_same_out_biz_no(
    client: TestClient,
    auth_service: AuthService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_read_users(auth_service, with_follow_graph=True)
    transfer_id, out_biz_no = _approved_transfer(client, uploader_headers=build_auth_headers(2, 2), title="待定转账重提")
    _set_transfer_status(transfer_id, "PENDING")
    service = get_payout_service()
    stub = _TransferGatewayStub(service.transfer_provider, query_results={out_biz_no: "NOT_FOUND"})
    monkeypatch.setattr(service, "transfer_provider", stub)

    with session_scope() as session:
        service.refresh_pending_transfers(session)

    assert stub.submitted == [out_biz_no]
    with session_scope() as session:
        transfer = get_finance_repo().get_payout_transfer(session, transfer_id)
        assert transfer is not None
        assert transfer.status == "SUBMITTED"


def test_failing_transfer_query_does_not_abort_the_refresh_job(
    client: TestClient,
    auth_service: AuthService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_read_users(auth_service, with_follow_graph=True)
    first_id, first_biz_no = _approved_transfer(client, uploader_headers=build_auth_headers(2, 2), title="查询异常转账")
    service = get_payout_service()
    stub =_TransferGatewayStub(service.transfer_provider, query_results={first_biz_no: RuntimeError("gateway timeout")})
    monkeypatch.setattr(service, "transfer_provider", stub)

    with session_scope() as session:
        service.refresh_pending_transfers(session)  # must not raise

    with session_scope() as session:
        transfer = get_finance_repo().get_payout_transfer(session, first_id)
        assert transfer is not None
        assert transfer.status == "SUBMITTED"


def test_late_success_after_failed_is_recorded_as_ignored_on_the_notification(
    client: TestClient,
    auth_service: AuthService,
) -> None:
    seed_read_users(auth_service, with_follow_graph=True)
    _, out_biz_no = _approved_transfer(client, uploader_headers=build_auth_headers(2, 2), title="迟到成功审计")
    _gateway_status(client, out_biz_no, "FAILED")
    _gateway_success(client, out_biz_no)

    from sqlalchemy import select

    from app.models.finance import AlipayGatewayNotificationRecord

    with session_scope() as session:
        rows = [
            (row.process_result, row.processed)
            for row in session.scalars(
                select(AlipayGatewayNotificationRecord)
                .where(AlipayGatewayNotificationRecord.out_biz_no == out_biz_no)
                .order_by(AlipayGatewayNotificationRecord.id.asc())
            )
        ]
    assert rows == [("OK", True), ("IGNORED_TERMINAL_TRANSFER", False)]
