from __future__ import annotations

from typing import Any

import pytest

from app.core.config import Settings
from app.models.finance import PayoutTransferRecord
from app.providers.transfer import AlipayTransferProvider


class _FakeAlipayClient:
    def __init__(self, response: Any) -> None:
        self.response = response

    def api_alipay_fund_trans_uni_transfer(self, **_: Any) -> Any:
        return self.response


def _submit(monkeypatch: pytest.MonkeyPatch, response: Any) -> str:
    provider = AlipayTransferProvider(Settings())
    monkeypatch.setattr(provider, "_client", lambda: _FakeAlipayClient(response))
    transfer = PayoutTransferRecord(
        payout_application_id=1,
        uploader_id=2,
        out_biz_no="PO202609250001",
        amount=1800,
        payee_account="chengjin@example.com",
        payee_name="白山",
        status="SUBMITTED",
    )
    return provider.submit_transfer(transfer).status


def test_accepted_transfer_is_submitted(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _submit(monkeypatch, {"code": "10000", "order_id": "2026"}) == "SUBMITTED"


@pytest.mark.parametrize(
    "response",
    [
        None,
        {"code": "20000", "msg": "Service Currently Unavailable", "sub_code": "isp.unknow-error"},
        {"code": "40004", "sub_code": "SYSTEM_ERROR"},
    ],
)
def test_unknown_outcome_stays_pending_instead_of_failed(monkeypatch: pytest.MonkeyPatch, response: Any) -> None:
    # Alipay may still execute these transfers; marking them FAILED would release the
    # settlements for a second payout.
    assert _submit(monkeypatch, response) == "PENDING"


def test_definite_business_rejection_is_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _submit(monkeypatch, {"code": "40004", "sub_code": "PAYEE_NOT_EXIST", "sub_msg": "收款账号不存在"}) == "FAILED"
