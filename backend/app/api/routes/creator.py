from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_user_read_service, require_auth_context
from app.core.db import get_db_session
from app.core.response import api_ok
from app.core.security import AuthContext
from app.services.user_read_service import UserReadService


router = APIRouter(tags=["creator"])


@router.get("/api/creator/metrics")
def creator_metrics(
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: UserReadService = Depends(get_user_read_service),
) -> dict[str, object]:
    return api_ok(service.get_creator_metrics(session, auth.user_id or 0))
