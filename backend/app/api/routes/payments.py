from __future__ import annotations

from urllib.parse import parse_qsl

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_payment_service, get_payout_service, require_auth_context, require_privileged_auth_context
from app.core.db import get_db_session
from app.core.response import api_ok
from app.core.security import AuthContext
from app.schemas.finance import AlipayCreatePayload
from app.services.payment_service import PaymentService
from app.services.payout_service import PayoutService


router = APIRouter(tags=["payments"])

MAX_CALLBACK_BODY_BYTES = 64 * 1024
MAX_CALLBACK_FIELDS = 64
MAX_CALLBACK_KEY_CHARS = 128
MAX_CALLBACK_VALUE_CHARS = 16 * 1024


async def _parse_callback_params(request: Request) -> dict[str, str]:
    content_length = request.headers.get("content-length", "").strip()
    if content_length.isdigit() and int(content_length) > MAX_CALLBACK_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Payment callback is too large")

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_CALLBACK_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Payment callback is too large")

    encoded = bytes(body)
    if not encoded:
        encoded = request.scope.get("query_string", b"")
        if len(encoded) > MAX_CALLBACK_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Payment callback is too large")
    elif not request.headers.get("content-type", "").lower().startswith("application/x-www-form-urlencoded"):
        raise HTTPException(status_code=415, detail="Unsupported payment callback content type")

    try:
        pairs = parse_qsl(
            encoded.decode("utf-8"),
            keep_blank_values=True,
            max_num_fields=MAX_CALLBACK_FIELDS,
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid payment callback form") from exc

    params: dict[str, str] = {}
    for key, value in pairs:
        if len(key) > MAX_CALLBACK_KEY_CHARS or len(value) > MAX_CALLBACK_VALUE_CHARS:
            raise HTTPException(status_code=413, detail="Payment callback field is too large")
        params[key] = value
    return params


@router.post("/api/alipay-payments")
@router.post("/api/pay/alipay/create", include_in_schema=False)
def create_alipay_payment(
    payload: AlipayCreatePayload,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: PaymentService = Depends(get_payment_service),
) -> dict[str, object]:
    return api_ok(
        service.create_alipay_payment(
            session,
            user_id=auth.user_id or 0,
            order_id=payload.orderId,
            material_id=payload.materialId,
        )
    )


@router.post("/api/alipay-payment-notifications", response_class=PlainTextResponse)
@router.post("/api/pay/alipay/notify", response_class=PlainTextResponse, include_in_schema=False)
async def alipay_notify(
    request: Request,
    session: Session = Depends(get_db_session),
    service: PaymentService = Depends(get_payment_service),
) -> str:
    params = await _parse_callback_params(request)
    return await run_in_threadpool(service.handle_alipay_notify, session, params)


@router.post("/api/alipay-gateway-notifications", response_class=PlainTextResponse)
@router.post("/api/pay/alipay/gateway", response_class=PlainTextResponse, include_in_schema=False)
async def alipay_gateway(
    request: Request,
    session: Session = Depends(get_db_session),
    service: PayoutService = Depends(get_payout_service),
) -> str:
    params = await _parse_callback_params(request)
    return await run_in_threadpool(service.handle_gateway_notification, session, params)


@router.get("/api/pay/orders/status", include_in_schema=False)
def pay_order_status(
    orderNo: str,
    force: bool | None = None,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: PaymentService = Depends(get_payment_service),
) -> dict[str, object]:
    return api_ok(service.get_order_status(session, user_id=auth.user_id or 0, out_trade_no=orderNo, force_check=bool(force)))


@router.get("/api/alipay-payments/{out_trade_no}")
@router.get("/api/pay/alipay/query", include_in_schema=False)
def alipay_query(
    out_trade_no: str,
    _: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: PaymentService = Depends(get_payment_service),
) -> dict[str, object]:
    return api_ok(service.query_alipay(session, out_trade_no=out_trade_no))
