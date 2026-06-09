from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import get_agent_feedback_service, get_ai_service, require_auth_context
from app.core.db import get_db_session
from app.core.response import api_ok
from app.core.security import AuthContext
from app.schemas.ai import AiChatRequestPayload, AiFeedbackPayload, AiMemoryPreferencePayload, AiRecommendRequestPayload
from app.services.agent_feedback_service import AgentFeedbackService
from app.services.ai_service import AiService


router = APIRouter(tags=["ai"])


@router.post("/api/ai-chats")
@router.post("/api/ai/chat")
def ai_chat(
    payload: AiChatRequestPayload,
    _: AuthContext = Depends(require_auth_context),
    service: AiService = Depends(get_ai_service),
) -> dict[str, object]:
    return api_ok(service.chat(payload))


@router.post("/api/ai-recommendations")
@router.post("/api/ai/recommend")
def ai_recommend(
    payload: AiRecommendRequestPayload,
    request: Request,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: AiService = Depends(get_ai_service),
) -> dict[str, object]:
    personal_memory_enabled = service.resolve_personal_memory_enabled(
        request.cookies.get(service.memory_cookie_name())
    )
    return api_ok(
        service.recommend(
            session,
            payload,
            current_user_id=auth.user_id,
            personal_memory_enabled=personal_memory_enabled,
        )
    )


@router.get("/api/ai/memory")
def ai_memory_preview(
    request: Request,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: AiService = Depends(get_ai_service),
) -> dict[str, object]:
    personal_memory_enabled = service.resolve_personal_memory_enabled(
        request.cookies.get(service.memory_cookie_name())
    )
    return api_ok(
        service.preview_memory(
            session,
            current_user_id=auth.user_id or 0,
            personal_memory_enabled=personal_memory_enabled,
        )
    )


@router.put("/api/ai/memory-preferences")
def update_ai_memory_preferences(
    payload: AiMemoryPreferencePayload,
    response: Response,
    _: AuthContext = Depends(require_auth_context),
    service: AiService = Depends(get_ai_service),
) -> dict[str, object]:
    service.write_personal_memory_preference_cookie(response, enabled=payload.enabled)
    return api_ok(service.memory_preference_payload(enabled=payload.enabled))


@router.delete("/api/ai/memory")
def delete_ai_memory(
    response: Response,
    _: AuthContext = Depends(require_auth_context),
    service: AiService = Depends(get_ai_service),
) -> dict[str, object]:
    service.write_personal_memory_preference_cookie(response, enabled=False)
    return api_ok(service.delete_personal_memory_payload())


@router.post("/api/ai/feedback")
def create_ai_feedback(
    payload: AiFeedbackPayload,
    request: Request,
    _: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: AiService = Depends(get_ai_service),
    feedback_service: AgentFeedbackService = Depends(get_agent_feedback_service),
) -> dict[str, object]:
    personal_memory_enabled = service.resolve_personal_memory_enabled(
        request.cookies.get(service.memory_cookie_name())
    )
    return api_ok(
        feedback_service.process_feedback(
            session,
            payload,
            personal_memory_enabled=personal_memory_enabled,
        )
    )
