from __future__ import annotations

import json
import logging

import anyio
from anyio import BrokenResourceError, ClosedResourceError, EndOfStream, WouldBlock
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_agent_feedback_service, get_ai_service, require_privileged_auth_context
from app.core.config import get_settings
from app.core.db import get_db_session, get_session_factory
from app.core.response import api_ok
from app.core.security import AuthContext
from app.schemas.ai import AiChatRequestPayload, AiFeedbackPayload, AiMemoryPreferencePayload, AiRecommendRequestPayload
from app.services.agent_feedback_service import AgentFeedbackService
from app.services.ai_service import AiService


router = APIRouter(tags=["ai"])
logger = logging.getLogger(__name__)


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
async def ai_recommend_stream(
    payload: AiRecommendRequestPayload,
    request: Request,
    auth: AuthContext = Depends(require_privileged_auth_context),
    service: AiService = Depends(get_ai_service),
) -> StreamingResponse:
    settings = get_settings()
    personal_memory_enabled = service.resolve_personal_memory_enabled(
        request.cookies.get(service.memory_cookie_name())
    )
    limiter = getattr(request.app.state, "ai_stream_limiter", None)
    if limiter is None:
        limiter = anyio.CapacityLimiter(max(1, settings.ai_agent_stream_max_concurrency))
        request.app.state.ai_stream_limiter = limiter
    request_id = str(getattr(request.state, "request_id", "") or "")

    async def events():
        send_stream, receive_stream = anyio.create_memory_object_stream[
            tuple[str, dict[str, object]]
        ](max_buffer_size=max(1, settings.ai_agent_stream_buffer_size))

        async def worker() -> None:
            acquired = False
            try:
                try:
                    limiter.acquire_nowait()
                    acquired = True
                except WouldBlock:
                    await send_stream.send(
                        (
                            "error",
                            {
                                "code": "AI_STREAM_BUSY",
                                "message": "StudyHub 学习辅导当前请求较多，请稍后重试",
                                "requestId": request_id,
                            },
                        )
                    )
                    return

                def run_recommendation() -> dict[str, object]:
                    session = get_session_factory()()

                    def emit_stage(stage: str) -> None:
                        try:
                            anyio.from_thread.run(
                                send_stream.send,
                                ("stage", {"stage": stage}),
                            )
                        except (BrokenResourceError, ClosedResourceError):
                            return

                    try:
                        return service.recommend(
                            session,
                            payload,
                            current_user_id=auth.user_id,
                            current_user_role_mask=auth.role_mask,
                            personal_memory_enabled=personal_memory_enabled,
                            stage_callback=emit_stage,
                        )
                    finally:
                        session.close()

                result = await anyio.to_thread.run_sync(run_recommendation)
                answer_delta = _agent_answer_delta(result)
                if answer_delta:
                    await send_stream.send(("delta", {"delta": answer_delta}))
                await send_stream.send(("result", result))
            except (BrokenResourceError, ClosedResourceError):
                return
            except Exception:  # noqa: BLE001
                logger.exception(
                    "AI recommendation stream failed",
                    extra={"event": "ai_stream_failed", "request_id": request_id},
                )
                try:
                    await send_stream.send(
                        (
                            "error",
                            {
                                "code": "AI_STREAM_FAILED",
                                "message": "StudyHub 学习辅导暂时无法回答",
                                "requestId": request_id,
                            },
                        )
                    )
                except (BrokenResourceError, ClosedResourceError):
                    return
            finally:
                if acquired:
                    limiter.release()
                await send_stream.aclose()

        async with anyio.create_task_group() as task_group:
            task_group.start_soon(worker)
            async with receive_stream:
                while True:
                    if await request.is_disconnected():
                        task_group.cancel_scope.cancel()
                        break
                    with anyio.move_on_after(max(1.0, settings.ai_agent_stream_heartbeat_seconds)) as scope:
                        try:
                            event, data = await receive_stream.receive()
                        except EndOfStream:
                            break
                    if scope.cancel_called:
                        yield ": keep-alive\n\n"
                        continue
                    yield _sse_event(event, data)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


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
