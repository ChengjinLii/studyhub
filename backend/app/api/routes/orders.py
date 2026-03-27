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


@router.get("/api/orders/{id}")
def get_order(
    id: int,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: PaymentService = Depends(get_payment_service),
) -> dict[str, object]:
    return api_ok(service.get_order(session, id, auth.user_id or 0))


@router.post("/api/orders/{id}/confirm")
def confirm_order(
    id: int,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: PaymentService = Depends(get_payment_service),
) -> dict[str, object]:
    return api_ok(service.confirm_order(session, id, auth.user_id or 0))
