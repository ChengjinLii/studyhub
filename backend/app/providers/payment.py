from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
import html
from typing import Any, Mapping, Protocol
from urllib.parse import parse_qsl

from app.core.config import Settings
from app.models.finance import OrderRecord, PaymentRecord
from app.providers.alipay_support import build_alipay_client, gateway_url_for_env


@dataclass(slots=True)
class PaymentNotification:
    out_trade_no: str
    trade_no: str | None
    amount_cents: int | None
    sign_verified: bool = True


@dataclass(slots=True)
class RefundResult:
    success: bool
    refund_trade_no: str | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass(slots=True)
class RefundQueryResult:
    status: str
    refund_trade_no: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class PaymentGatewayProvider(Protocol):
    provider_name: str
    channel_name: str

    def build_checkout_payload(self, *, out_trade_no: str, order: OrderRecord) -> dict[str, Any]: ...

    def build_force_check_notification(self, *, out_trade_no: str, order: OrderRecord) -> PaymentNotification | None: ...

    def parse_notification(self, params: Mapping[str, str]) -> PaymentNotification: ...

    def build_query_payload(self, *, payment: PaymentRecord, order: OrderRecord | None) -> dict[str, Any]: ...

    def success_response_text(self) -> str: ...

    def probe(self, *, deep: bool = False) -> dict[str, Any]: ...

    def refund(self, *, out_trade_no: str, trade_no: str | None, refund_amount_cents: int, out_request_no: str) -> RefundResult: ...

    def query_refund(self, *, out_trade_no: str, trade_no: str | None, out_request_no: str) -> RefundQueryResult: ...


class LocalAlipayPaymentProvider:
    provider_name = "local_alipay"
    channel_name = "alipay_page"

    def build_checkout_payload(self, *, out_trade_no: str, order: OrderRecord) -> dict[str, Any]:
        return {
            "status": "CREATED",
            "orderId": order.id,
            "materialId": order.material_id,
            "orderNo": out_trade_no,
            "form": self._build_pay_form(out_trade_no),
        }

    def build_force_check_notification(self, *, out_trade_no: str, order: OrderRecord) -> PaymentNotification:
        return PaymentNotification(
            out_trade_no=out_trade_no,
            trade_no=self._build_trade_no(out_trade_no),
            amount_cents=int(order.amount or 0),
            sign_verified=True,
        )

    def parse_notification(self, params: Mapping[str, str]) -> PaymentNotification:
        out_trade_no = str(params.get("out_trade_no") or "").strip()
        raw_trade_no = str(params.get("trade_no") or "").strip()
        total_amount = str(params.get("total_amount") or "").strip() or None
        return PaymentNotification(
            out_trade_no=out_trade_no,
            trade_no=raw_trade_no or (self._build_trade_no(out_trade_no) if out_trade_no else None),
            amount_cents=self._parse_amount_to_cents(total_amount),
            sign_verified=bool(out_trade_no),
        )

    def build_query_payload(self, *, payment: PaymentRecord, order: OrderRecord | None) -> dict[str, Any]:
        return {
            "outTradeNo": payment.out_trade_no,
            "tradeNo": payment.trade_no,
            "status": payment.status,
            "amount": payment.amount,
            "channel": payment.channel,
            "orderId": order.id if order else None,
            "materialId": order.material_id if order else None,
            "paidAt": payment.paid_at.isoformat() if payment.paid_at else None,
        }

    def success_response_text(self) -> str:
        return "success"

    def probe(self, *, deep: bool = False) -> dict[str, Any]:
        del deep
        return {
            "status": "ok",
            "provider": self.provider_name,
            "channel": self.channel_name,
            "mode": "local-simulated",
        }

    def refund(self, *, out_trade_no: str, trade_no: str | None, refund_amount_cents: int, out_request_no: str) -> RefundResult:
        return RefundResult(success=True, refund_trade_no=f"REFUND-LOCAL-{out_request_no[-8:]}")

    def query_refund(self, *, out_trade_no: str, trade_no: str | None, out_request_no: str) -> RefundQueryResult:
        del out_trade_no, trade_no
        return RefundQueryResult(status="SUCCESS", refund_trade_no=f"REFUND-LOCAL-{out_request_no[-8:]}")

    def _build_pay_form(self, out_trade_no: str) -> str:
        escaped = html.escape(out_trade_no, quote=True)
        return (
            "<form id=\"studyhub-alipay-form\" method=\"GET\" action=\"/pay/result\">"
            f"<input type=\"hidden\" name=\"orderNo\" value=\"{escaped}\"/>"
            "</form>"
        )

    def _build_trade_no(self, out_trade_no: str) -> str:
        suffix = out_trade_no[-8:] if out_trade_no else datetime.now(UTC).strftime("%H%M%S")
        return f"ALI-LOCAL-{suffix}"

    def _parse_amount_to_cents(self, raw: str | None) -> int | None:
        if not raw:
            return None
        try:
            value = Decimal(raw)
        except Exception:  # noqa: BLE001
            return None
        return int((value * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


class AlipayPagePaymentProvider:
    provider_name = "alipay_page"
    channel_name = "alipay_page"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def build_checkout_payload(self, *, out_trade_no: str, order: OrderRecord) -> dict[str, Any]:
        client = self._client()
        total_amount = self._cents_to_amount(int(order.amount or 0))
        order_string = client.api_alipay_trade_page_pay(
            out_trade_no=out_trade_no,
            total_amount=total_amount,
            subject=order.material_title or f"StudyHub Order #{order.id}",
            return_url=self.settings.alipay_return_url,
            notify_url=self.settings.alipay_notify_url,
        )
        action = self._gateway_url()
        fields = "".join(
            f"<input type=\"hidden\" name=\"{html.escape(name, quote=True)}\" value=\"{html.escape(value, quote=True)}\"/>"
            for name, value in parse_qsl(order_string, keep_blank_values=True)
        )
        form = (
            f"<form id=\"studyhub-alipay-form\" method=\"GET\" action=\"{html.escape(action, quote=True)}\">"
            f"{fields}"
            "</form>"
        )
        return {
            "status": "CREATED",
            "orderId": order.id,
            "materialId": order.material_id,
            "orderNo": out_trade_no,
            "gatewayUrl": f"{action}?{order_string}",
            "form": form,
        }

    def build_force_check_notification(self, *, out_trade_no: str, order: OrderRecord) -> PaymentNotification | None:
        result = self._trade_query(out_trade_no)
        if not result:
            return None
        trade_status = str(result.get("trade_status") or "").upper()
        if trade_status not in {"TRADE_SUCCESS", "TRADE_FINISHED"}:
            return None
        return PaymentNotification(
            out_trade_no=out_trade_no,
            trade_no=str(result.get("trade_no") or "") or None,
            amount_cents=self._parse_amount_to_cents(str(result.get("total_amount") or "")),
            sign_verified=True,
        )

    def parse_notification(self, params: Mapping[str, str]) -> PaymentNotification:
        params_dict = {str(key): str(value) for key, value in params.items()}
        sign = params_dict.get("sign")
        payload = {key: value for key, value in params_dict.items() if key != "sign" and key != "sign_type"}
        sign_verified = bool(sign) and bool(self._client().verify(payload, sign))
        out_trade_no = str(params_dict.get("out_trade_no") or "").strip()
        trade_no = str(params_dict.get("trade_no") or "").strip() or None
        return PaymentNotification(
            out_trade_no=out_trade_no,
            trade_no=trade_no,
            amount_cents=self._parse_amount_to_cents(str(params_dict.get("total_amount") or "")),
            sign_verified=sign_verified,
        )

    def build_query_payload(self, *, payment: PaymentRecord, order: OrderRecord | None) -> dict[str, Any]:
        remote = self._trade_query(str(payment.out_trade_no or ""))
        return {
            "outTradeNo": payment.out_trade_no,
            "tradeNo": payment.trade_no,
            "status": payment.status,
            "amount": payment.amount,
            "channel": payment.channel,
            "orderId": order.id if order else None,
            "materialId": order.material_id if order else None,
            "paidAt": payment.paid_at.isoformat() if payment.paid_at else None,
            "providerQuery": remote,
        }

    def success_response_text(self) -> str:
        return "success"

    def probe(self, *, deep: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": "ok",
            "provider": self.provider_name,
            "channel": self.channel_name,
            "gateway": self._gateway_url(),
            "appId": self.settings.alipay_app_id,
            "environment": self.settings.alipay_env,
        }
        if deep:
            payload["clientReady"] = True
            self._client()
        return payload

    def refund(self, *, out_trade_no: str, trade_no: str | None, refund_amount_cents: int, out_request_no: str) -> RefundResult:
        client = self._client()
        refund_amount = self._cents_to_amount(refund_amount_cents)
        try:
            result = client.api_alipay_trade_refund(
                refund_amount=refund_amount,
                out_trade_no=out_trade_no,
                trade_no=trade_no,
                out_request_no=out_request_no,
            )
        except Exception as exc:  # noqa: BLE001
            return RefundResult(success=False, error_code="SDK_ERROR", error_message=str(exc)[:200])
        if not isinstance(result, dict):
            return RefundResult(success=False, error_code="INVALID_RESPONSE", error_message="non-dict response")
        code = str(result.get("code") or "")
        if code == "10000":
            return RefundResult(success=True, refund_trade_no=str(result.get("trade_no") or "") or None)
        return RefundResult(
            success=False,
            error_code=code,
            error_message=str(result.get("sub_msg") or result.get("msg") or "")[:200],
        )

    def query_refund(self, *, out_trade_no: str, trade_no: str | None, out_request_no: str) -> RefundQueryResult:
        try:
            result = self._client().api_alipay_trade_fastpay_refund_query(
                out_request_no=out_request_no,
                out_trade_no=out_trade_no,
                trade_no=trade_no,
            )
        except Exception as exc:  # noqa: BLE001
            return RefundQueryResult(status="UNKNOWN", error_code="SDK_ERROR", error_message=str(exc)[:200])
        if not isinstance(result, dict):
            return RefundQueryResult(status="UNKNOWN", error_code="INVALID_RESPONSE", error_message="non-dict response")
        code = str(result.get("code") or "")
        refund_status = str(result.get("refund_status") or "").strip().upper()
        if code == "10000" and refund_status == "REFUND_SUCCESS":
            return RefundQueryResult(
                status="SUCCESS",
                refund_trade_no=str(result.get("trade_no") or result.get("refund_detail_item_list") or "") or None,
            )
        if code == "20000":
            return RefundQueryResult(status="PENDING", error_code=code)
        return RefundQueryResult(
            status="NOT_FOUND" if code == "40004" else "UNKNOWN",
            error_code=code or None,
            error_message=str(result.get("sub_msg") or result.get("msg") or "")[:200] or None,
        )

    def _client(self):
        return build_alipay_client(self.settings)

    def _trade_query(self, out_trade_no: str) -> dict[str, Any] | None:
        if not out_trade_no:
            return None
        result = self._client().api_alipay_trade_query(out_trade_no=out_trade_no)
        return result if isinstance(result, dict) else None

    def _gateway_url(self) -> str:
        return gateway_url_for_env(self.settings.alipay_env)

    def _cents_to_amount(self, amount_cents: int) -> str:
        return str((Decimal(amount_cents) / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    def _parse_amount_to_cents(self, raw: str | None) -> int | None:
        if not raw:
            return None
        try:
            value = Decimal(raw)
        except Exception:  # noqa: BLE001
            return None
        return int((value * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
