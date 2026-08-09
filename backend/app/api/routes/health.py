from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.api.deps import get_health_service
from app.core.db import get_db_session
from app.core.observability import get_runtime_metrics
from app.core.response import api_ok
from app.services.health_service import HealthService


router = APIRouter(tags=["health"])


@router.get("/healthz")
@router.get("/api/healthz")
def healthz(
    service: HealthService = Depends(get_health_service),
) -> dict[str, object]:
    return api_ok(service.build_public_payload())


@router.get("/readyz")
@router.get("/api/readyz")
def readyz(
    deep: bool = Query(default=False),
    session: Session = Depends(get_db_session),
    service: HealthService = Depends(get_health_service),
) -> dict[str, object]:
    return api_ok(service.build_readiness_payload(session, deep=deep))


@router.get("/metrics", response_class=PlainTextResponse)
@router.get("/api/metrics", response_class=PlainTextResponse)
def metrics(service: HealthService = Depends(get_health_service)) -> str:
    return get_runtime_metrics().render_prometheus(service.settings)
