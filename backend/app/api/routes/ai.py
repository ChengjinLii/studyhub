from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_ai_service, require_auth_context
from app.core.db import get_db_session
from app.core.response import api_ok
from app.core.security import AuthContext
from app.schemas.ai import AiChatRequestPayload, AiRecommendRequestPayload
from app.services.ai_service import AiService


router = APIRouter(tags=["ai"])


@router.post("/api/ai-chats")
@router.post("/api/ai/chat", include_in_schema=False)
def ai_chat(
    payload: AiChatRequestPayload,
    _: AuthContext = Depends(require_auth_context),
    service: AiService = Depends(get_ai_service),
) -> dict[str, object]:
    return api_ok(service.chat(payload))


@router.post("/api/ai-recommendations")
@router.post("/api/ai/recommend", include_in_schema=False)
def ai_recommend(
    payload: AiRecommendRequestPayload,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: AiService = Depends(get_ai_service),
) -> dict[str, object]:
    return api_ok(service.recommend(session, payload, current_user_id=auth.user_id))
