from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import require_enabled_admin_agent_context
from app.core.config import get_settings
from app.core.response import api_ok
from app.core.security import AuthContext


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
