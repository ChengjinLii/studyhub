from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.api.deps import get_payment_service, get_payout_service, require_auth_context, require_privileged_auth_context
from app.core.db import get_db_session
from app.core.response import api_ok
from app.core.security import AuthContext
from app.schemas.finance import AlipayCreatePayload
from app.services.payment_service import PaymentService
from app.services.payout_service import PayoutService


router = APIRouter(tags=["payments"])


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
    form = await request.form()
    params = {key: str(value) for key, value in form.items()}
    if not params:
        params = {key: value for key, value in request.query_params.items()}
    return service.handle_alipay_notify(session, params)


@router.post("/api/alipay-gateway-notifications", response_class=PlainTextResponse)
@router.post("/api/pay/alipay/gateway", response_class=PlainTextResponse, include_in_schema=False)
async def alipay_gateway(
    request: Request,
    session: Session = Depends(get_db_session),
    service: PayoutService = Depends(get_payout_service),
) -> str:
    form = await request.form()
    params = {key: str(value) for key, value in form.items()}
    if not params:
        params = {key: value for key, value in request.query_params.items()}
    return service.handle_gateway_notification(session, params)


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
