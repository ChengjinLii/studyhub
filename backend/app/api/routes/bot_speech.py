from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.deps import get_bot_speech_service, require_privileged_auth_context
from app.core.db import get_db_session
from app.core.response import api_ok
from app.core.security import AuthContext
from app.schemas.bot_speech import BotSpeechUpdatePayload
from app.services.bot_speech_service import BotSpeechService


router = APIRouter(tags=["bot-speech"])


@router.get("/api/bot-speech")
def get_bot_speech(
    response: Response,
    session: Session = Depends(get_db_session),
    service: BotSpeechService = Depends(get_bot_speech_service),
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    return api_ok(service.get_config(session))


@router.put("/api/admin/bot-speech")
def update_bot_speech(
    payload: BotSpeechUpdatePayload,
    auth: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: BotSpeechService = Depends(get_bot_speech_service),
) -> dict[str, object]:
    return api_ok(
        service.update_config(
            session,
            admin_user_id=auth.user_id or 0,
            payload=payload,
        )
    )
