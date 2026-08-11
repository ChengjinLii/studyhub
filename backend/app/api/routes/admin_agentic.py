from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.agentic_platform.application import (
    AdminAgentRunService,
    AdminRunConflictError,
    AdminRunNotFoundError,
    ResumeTokenRejectedError,
)
from app.api.deps import (
    get_admin_agent_run_service,
    require_enabled_admin_agent_context,
    require_enabled_deep_research_admin_context,
)
from app.core.config import get_settings
from app.core.db import get_db_session
from app.core.response import api_ok
from app.core.security import AuthContext
from app.schemas.agentic import (
    AgentRunCancelPayload,
    AgentRunCreatePayload,
    AgentRunResumePayload,
    DeepResearchCreatePayload,
)


router = APIRouter(tags=["admin-agentic"])


@router.get("/api/admin/agent-runs/health", include_in_schema=False)
def agentic_platform_health(
    _: AuthContext = Depends(require_enabled_admin_agent_context),
) -> dict[str, object]:
    """PR 1 readiness probe; future run APIs remain isolated under this route family."""

    settings = get_settings()
    return api_ok(
        {
            "status": "ready",
            "runtime": settings.agentic_runtime,
        }
    )


@router.get("/api/admin/agent-runs", include_in_schema=False)
def list_agent_runs(
    limit: int = Query(default=30, ge=1, le=100),
    run_status: str | None = Query(default=None, alias="status", max_length=32),
    auth: AuthContext = Depends(require_enabled_admin_agent_context),
    session: Session = Depends(get_db_session),
    service: AdminAgentRunService = Depends(get_admin_agent_run_service),
) -> dict[str, object]:
    try:
        return api_ok(
            service.list_runs(
                session,
                admin_actor_id=_require_actor_id(auth),
                limit=limit,
                status=run_status,
            )
        )
    except Exception as exc:  # noqa: BLE001 - mapped to the established API envelope below.
        raise _agentic_http_error(exc) from exc


@router.post("/api/admin/agent-runs", include_in_schema=False)
def create_agent_run(
    payload: AgentRunCreatePayload,
    auth: AuthContext = Depends(require_enabled_admin_agent_context),
    session: Session = Depends(get_db_session),
    service: AdminAgentRunService = Depends(get_admin_agent_run_service),
) -> dict[str, object]:
    try:
        return api_ok(service.create_run(session, admin_actor_id=_require_actor_id(auth), payload=payload))
    except Exception as exc:  # noqa: BLE001 - mapped to the established API envelope below.
        raise _agentic_http_error(exc) from exc


@router.get("/api/admin/agent-runs/{run_id}/events", include_in_schema=False)
def stream_agent_run_events(
    run_id: str,
    after: int = Query(default=0, ge=0),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    auth: AuthContext = Depends(require_enabled_admin_agent_context),
    session: Session = Depends(get_db_session),
    service: AdminAgentRunService = Depends(get_admin_agent_run_service),
) -> StreamingResponse:
    resume_after = max(after, _parse_event_sequence(last_event_id))
    try:
        admin_actor_id = _require_actor_id(auth)
        snapshot = service.get_run(session, run_id=run_id, admin_actor_id=admin_actor_id)
        events = service.list_events(
            session,
            run_id=run_id,
            admin_actor_id=admin_actor_id,
            after_sequence=resume_after,
        )["events"]
    except Exception as exc:  # noqa: BLE001 - mapped to the established API envelope below.
        raise _agentic_http_error(exc) from exc

    def event_stream():
        # The stream is deliberately finite. EventSource reconnects with
        # Last-Event-ID, receives a fresh durable snapshot, then any missed
        # append-only events. This avoids holding a request-scoped DB session.
        yield "retry: 2000\n\n"
        yield _sse_event("run.snapshot", snapshot)
        for event in events:
            event_name = event.get("name") if isinstance(event.get("name"), str) else "runtime.unknown"
            event_id = str(event.get("sequence")) if isinstance(event.get("sequence"), int) else None
            yield _sse_event(event_name, event, event_id=event_id)
        yield ": reconnect for durable updates\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@router.get("/api/admin/agent-runs/{run_id}", include_in_schema=False)
def get_agent_run(
    run_id: str,
    auth: AuthContext = Depends(require_enabled_admin_agent_context),
    session: Session = Depends(get_db_session),
    service: AdminAgentRunService = Depends(get_admin_agent_run_service),
) -> dict[str, object]:
    try:
        return api_ok(service.get_run(session, run_id=run_id, admin_actor_id=_require_actor_id(auth)))
    except Exception as exc:  # noqa: BLE001 - mapped to the established API envelope below.
        raise _agentic_http_error(exc) from exc


@router.post("/api/admin/agent-runs/{run_id}/resume", include_in_schema=False)
def resume_agent_run(
    run_id: str,
    payload: AgentRunResumePayload,
    auth: AuthContext = Depends(require_enabled_admin_agent_context),
    session: Session = Depends(get_db_session),
    service: AdminAgentRunService = Depends(get_admin_agent_run_service),
) -> dict[str, object]:
    try:
        return api_ok(
            service.resume(
                session,
                run_id=run_id,
                admin_actor_id=_require_actor_id(auth),
                wait_id=payload.waitId,
                resume_token=payload.resumeToken,
                payload=payload.payload,
            )
        )
    except Exception as exc:  # noqa: BLE001 - mapped to the established API envelope below.
        raise _agentic_http_error(exc) from exc


@router.post("/api/admin/agent-runs/{run_id}/cancel", include_in_schema=False)
def cancel_agent_run(
    run_id: str,
    payload: AgentRunCancelPayload,
    auth: AuthContext = Depends(require_enabled_admin_agent_context),
    session: Session = Depends(get_db_session),
    service: AdminAgentRunService = Depends(get_admin_agent_run_service),
) -> dict[str, object]:
    try:
        return api_ok(
            service.cancel(
                session,
                run_id=run_id,
                admin_actor_id=_require_actor_id(auth),
                reason=payload.reason,
            )
        )
    except Exception as exc:  # noqa: BLE001 - mapped to the established API envelope below.
        raise _agentic_http_error(exc) from exc


@router.post("/api/admin/deep-research", include_in_schema=False)
def create_deep_research_run(
    payload: DeepResearchCreatePayload,
    auth: AuthContext = Depends(require_enabled_deep_research_admin_context),
    session: Session = Depends(get_db_session),
    service: AdminAgentRunService = Depends(get_admin_agent_run_service),
) -> dict[str, object]:
    try:
        return api_ok(service.create_deep_research(session, admin_actor_id=_require_actor_id(auth), payload=payload))
    except Exception as exc:  # noqa: BLE001 - mapped to the established API envelope below.
        raise _agentic_http_error(exc) from exc


@router.get("/api/admin/agent-artifacts", include_in_schema=False)
def list_agent_artifacts(
    run_id: str | None = Query(default=None, alias="runId", max_length=64),
    artifact_type: str | None = Query(default=None, alias="artifactType", max_length=128),
    limit: int = Query(default=50, ge=1, le=100),
    auth: AuthContext = Depends(require_enabled_admin_agent_context),
    session: Session = Depends(get_db_session),
    service: AdminAgentRunService = Depends(get_admin_agent_run_service),
) -> dict[str, object]:
    try:
        return api_ok(
            service.list_artifacts(
                session,
                admin_actor_id=_require_actor_id(auth),
                run_id=run_id,
                artifact_type=artifact_type,
                limit=limit,
            )
        )
    except Exception as exc:  # noqa: BLE001 - mapped to the established API envelope below.
        raise _agentic_http_error(exc) from exc


def _require_actor_id(auth: AuthContext) -> int:
    if auth.user_id is None or auth.user_id <= 0:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    return auth.user_id


def _parse_event_sequence(value: str | None) -> int:
    if value is None:
        return 0
    try:
        return max(0, int(value))
    except ValueError:
        return 0


def _sse_event(event: str, payload: object, *, event_id: str | None = None) -> str:
    identifier = f"id: {event_id}\n" if event_id else ""
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"{identifier}event: {event}\ndata: {data}\n\n"


def _agentic_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, AdminRunNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "AGENT_RUN_NOT_FOUND", "message": "Agent run was not found."},
        )
    if isinstance(exc, (ResumeTokenRejectedError, AdminRunConflictError)):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code, "message": str(exc)},
        )
    if isinstance(exc, ValueError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_AGENTIC_REQUEST", "message": "Agentic request is invalid."},
        )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={"code": "AGENTIC_CONTROL_PLANE_ERROR", "message": "Agentic control plane is temporarily unavailable."},
    )
