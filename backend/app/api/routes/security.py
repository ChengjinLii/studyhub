from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.core.observability import get_runtime_metrics
from app.core.response import api_ok


router = APIRouter(tags=["security"])


@router.post("/api/security/csp-reports")
async def collect_csp_report(request: Request) -> dict[str, object]:
    payload: dict[str, Any] = {}
    try:
        body = await request.json()
        if isinstance(body, dict):
            payload = body
    except Exception:
        payload = {}
    report = payload.get("csp-report") if isinstance(payload.get("csp-report"), dict) else payload
    directive = report.get("violated-directive") if isinstance(report, dict) else None
    get_runtime_metrics().record_security_event(
        event="csp_report",
        reason=str(directive or "unknown")[:80],
    )
    return api_ok()
