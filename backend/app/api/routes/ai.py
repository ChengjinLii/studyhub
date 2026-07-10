from __future__ import annotations

import json
from queue import Queue
from threading import Thread

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_agent_feedback_service, get_ai_service, require_privileged_auth_context
from app.core.db import get_db_session, get_session_factory
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
    _: AuthContext = Depends(require_privileged_auth_context),
    service: AiService = Depends(get_ai_service),
) -> dict[str, object]:
    return api_ok(service.chat(payload))


@router.post("/api/ai-recommendations")
@router.post("/api/ai/recommend")
def ai_recommend(
    payload: AiRecommendRequestPayload,
    request: Request,
    auth: AuthContext = Depends(require_privileged_auth_context),
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
            current_user_role_mask=auth.role_mask,
            personal_memory_enabled=personal_memory_enabled,
        )
    )


@router.post("/api/ai-recommendations/stream")
@router.post("/api/ai/recommend/stream")
def ai_recommend_stream(
    payload: AiRecommendRequestPayload,
    request: Request,
    auth: AuthContext = Depends(require_privileged_auth_context),
    service: AiService = Depends(get_ai_service),
) -> StreamingResponse:
    personal_memory_enabled = service.resolve_personal_memory_enabled(
        request.cookies.get(service.memory_cookie_name())
    )

    def events():
        queue: Queue[tuple[str, dict[str, object]] | None] = Queue()

        def emit(event: str, data: dict[str, object]) -> None:
            queue.put((event, data))

        def emit_stage(stage: str) -> None:
            emit("stage", {"stage": stage})

        def worker() -> None:
            session = get_session_factory()()
            try:
                result = service.recommend(
                    session,
                    payload,
                    current_user_id=auth.user_id,
                    current_user_role_mask=auth.role_mask,
                    personal_memory_enabled=personal_memory_enabled,
                    stage_callback=emit_stage,
                )
                answer_delta = _agent_answer_delta(result)
                if answer_delta:
                    emit("delta", {"delta": answer_delta})
                emit("result", result)
            except Exception as exc:
                emit("error", {"message": str(exc) or "StudyHub 学习辅导暂时无法回答"})
            finally:
                session.close()
                queue.put(None)

        Thread(target=worker, daemon=True).start()
        while True:
            item = queue.get()
            if item is None:
                break
            event, data = item
            yield _sse_event(event, data)

    return StreamingResponse(events(), media_type="text/event-stream")


@router.get("/api/ai/memory")
def ai_memory_preview(
    request: Request,
    auth: AuthContext = Depends(require_privileged_auth_context),
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


def _sse_event(event: str, payload: dict[str, object]) -> str:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {data}\n\n"


def _agent_answer_delta(result: dict[str, object]) -> str:
    output = result.get("output")
    if not isinstance(output, str):
        return ""
    start = output.find("<json>")
    end = output.find("</json>")
    body = output[start + 6 : end].strip() if start >= 0 and end > start else output.strip()
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return ""
    if not isinstance(parsed, dict):
        return ""
    answer = parsed.get("answer")
    return answer.strip() if isinstance(answer, str) else ""


@router.put("/api/ai/memory-preferences")
def update_ai_memory_preferences(
    payload: AiMemoryPreferencePayload,
    response: Response,
    _: AuthContext = Depends(require_privileged_auth_context),
    service: AiService = Depends(get_ai_service),
) -> dict[str, object]:
    service.write_personal_memory_preference_cookie(response, enabled=payload.enabled)
    return api_ok(service.memory_preference_payload(enabled=payload.enabled))


@router.delete("/api/ai/memory")
def delete_ai_memory(
    response: Response,
    auth: AuthContext = Depends(require_privileged_auth_context),
    service: AiService = Depends(get_ai_service),
) -> dict[str, object]:
    service.write_personal_memory_preference_cookie(response, enabled=False)
    return api_ok(service.delete_personal_memory_payload(current_user_id=auth.user_id))


@router.post("/api/ai/feedback")
def create_ai_feedback(
    payload: AiFeedbackPayload,
    request: Request,
    _: AuthContext = Depends(require_privileged_auth_context),
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
