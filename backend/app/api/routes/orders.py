from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_payment_service, require_auth_context
from app.core.db import get_db_session
from app.core.response import api_ok
from app.core.security import AuthContext
from app.schemas.finance import OrderCreatePayload
from app.services.payment_service import PaymentService


router = APIRouter(tags=["orders"])


@router.post("/api/orders")
def create_order(
    payload: OrderCreatePayload,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: PaymentService = Depends(get_payment_service),
) -> dict[str, object]:
    return api_ok(service.create_order(session, auth.user_id or 0, material_id=payload.materialId, channel=payload.channel))


@router.get("/api/orders/status")
def get_order_status(
    orderNo: str,
    force: bool | None = None,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: PaymentService = Depends(get_payment_service),
) -> dict[str, object]:
    return api_ok(service.get_order_status(session, user_id=auth.user_id or 0, out_trade_no=orderNo, force_check=bool(force)))


@router.get("/api/orders/{id}")
def get_order(
    id: int,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: PaymentService = Depends(get_payment_service),
) -> dict[str, object]:
    return api_ok(service.get_order(session, id, auth.user_id or 0))


@router.put("/api/orders/{id}/confirmation")
@router.post("/api/orders/{id}/confirm")
def confirm_order(
    id: int,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: PaymentService = Depends(get_payment_service),
) -> dict[str, object]:
    return api_ok(service.confirm_order(session, id, auth.user_id or 0))
