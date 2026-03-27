from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Mapping, Protocol

from app.core.config import Settings
from app.models.finance import PayoutTransferRecord
from app.providers.alipay_support import build_alipay_client


@dataclass(slots=True)
class TransferResult:
    status: str
    provider_name: str
    alipay_order_id: str | None = None
    pay_fund_order_id: str | None = None
    failure_reason: str | None = None


@dataclass(slots=True)
class TransferGatewayNotification:
    out_biz_no: str
    status: str
    sign_verified: bool
    event_id: str | None


class PayoutTransferProvider(Protocol):
    provider_name: str

    def submit_transfer(self, transfer: PayoutTransferRecord) -> TransferResult: ...

    def query_transfer(self, transfer: PayoutTransferRecord) -> TransferResult: ...

    def parse_gateway_notification(self, params: Mapping[str, str]) -> TransferGatewayNotification: ...

    def success_response_text(self) -> str: ...

    def probe(self, *, deep: bool = False) -> dict[str, Any]: ...


class LocalTransferProvider:
    provider_name = "local_transfer"

    def submit_transfer(self, transfer: PayoutTransferRecord) -> TransferResult:
        return TransferResult(
            status="SUBMITTED",
            provider_name=self.provider_name,
            alipay_order_id=transfer.alipay_order_id,
            pay_fund_order_id=transfer.pay_fund_order_id,
        )

    def query_transfer(self, transfer: PayoutTransferRecord) -> TransferResult:
        return TransferResult(
            status="SUCCESS",
            provider_name=self.provider_name,
            alipay_order_id=transfer.alipay_order_id or f"ALI{transfer.id or 0:08d}",
            pay_fund_order_id=transfer.pay_fund_order_id or f"FUND{transfer.id or 0:08d}",
        )

    def parse_gateway_notification(self, params: Mapping[str, str]) -> TransferGatewayNotification:
        return TransferGatewayNotification(
            out_biz_no=str(params.get("out_biz_no") or "").strip(),
            status=str(params.get("status") or "").strip().upper() or "PENDING",
            sign_verified=bool(params.get("out_biz_no")),
            event_id=str(params.get("notify_id") or params.get("msg_id") or params.get("event_id") or "").strip() or None,
        )

    def success_response_text(self) -> str:
        return "success"

    def probe(self, *, deep: bool = False) -> dict[str, Any]:
        del deep
        return {
            "status": "ok",
            "provider": self.provider_name,
            "mode": "local-simulated",
        }


class AlipayTransferProvider:
    provider_name = "alipay_transfer"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def submit_transfer(self, transfer: PayoutTransferRecord) -> TransferResult:
        client = self._client()
        result = client.api_alipay_fund_trans_uni_transfer(
            out_biz_no=transfer.out_biz_no,
            trans_amount=self._cents_to_amount(int(transfer.amount or 0)),
            product_code="TRANS_ACCOUNT_NO_PWD",
            biz_scene="DIRECT_TRANSFER",
            order_title=f"StudyHub Payout #{transfer.payout_application_id}",
            payee_info={
                "identity": transfer.payee_account,
                "identity_type": "ALIPAY_LOGON_ID",
                "name": transfer.payee_name,
            },
        )
        if not isinstance(result, dict):
            return TransferResult(status="FAILED", provider_name=self.provider_name, failure_reason="支付宝转账返回为空")
        code = str(result.get("code") or "")
        sub_code = str(result.get("sub_code") or "")
        success = code == "10000"
        return TransferResult(
            status="SUBMITTED" if success else "FAILED",
            provider_name=self.provider_name,
            alipay_order_id=str(result.get("order_id") or "") or None,
            pay_fund_order_id=str(result.get("pay_fund_order_id") or "") or None,
            failure_reason=None if success else (sub_code or str(result.get("sub_msg") or result.get("msg") or "支付宝转账失败")),
        )

    def query_transfer(self, transfer: PayoutTransferRecord) -> TransferResult:
        client = self._client()
        result = client.api_alipay_fund_trans_common_query(out_biz_no=transfer.out_biz_no)
        if not isinstance(result, dict):
            return TransferResult(status="PENDING", provider_name=self.provider_name)
        status_value = str(result.get("status") or result.get("order_status") or "").upper()
        normalized = "SUCCESS" if status_value in {"SUCCESS", "PAY_SUCCESS"} else ("FAILED" if status_value in {"FAIL", "FAILED"} else "PENDING")
        return TransferResult(
            status=normalized,
            provider_name=self.provider_name,
            alipay_order_id=str(result.get("order_id") or "") or None,
            pay_fund_order_id=str(result.get("pay_fund_order_id") or "") or None,
            failure_reason=str(result.get("fail_reason") or result.get("sub_msg") or "").strip() or None,
        )

    def parse_gateway_notification(self, params: Mapping[str, str]) -> TransferGatewayNotification:
        params_dict = {str(key): str(value) for key, value in params.items()}
        sign = params_dict.get("sign")
        payload = {key: value for key, value in params_dict.items() if key != "sign" and key != "sign_type"}
        sign_verified = bool(sign) and bool(self._client().verify(payload, sign))
        return TransferGatewayNotification(
            out_biz_no=str(params_dict.get("out_biz_no") or "").strip(),
            status=str(params_dict.get("status") or "").strip().upper() or "PENDING",
            sign_verified=sign_verified,
            event_id=str(params_dict.get("notify_id") or params_dict.get("msg_id") or params_dict.get("event_id") or "").strip() or None,
        )

    def success_response_text(self) -> str:
        return "success"

    def probe(self, *, deep: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": "ok",
            "provider": self.provider_name,
            "environment": self.settings.alipay_env,
            "appId": self.settings.alipay_app_id,
        }
        if deep:
            self._client()
            payload["clientReady"] = True
        return payload

    def _client(self):
        return build_alipay_client(self.settings)

    def _cents_to_amount(self, amount_cents: int) -> str:
        return str((Decimal(amount_cents) / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
