"""Short-lived delegated access to one intake batch; never a website login."""
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import get_auth_repo, get_optional_auth_context, get_token_codec
from app.core.db import get_db_session
from app.core.security import AuthContext
from app.services.read_support import ROLE_ADMIN, ROLE_DEVELOPER


def require_batch_admin(
    request: Request,
    auth: AuthContext | None = Depends(get_optional_auth_context),
    session: Session = Depends(get_db_session),
) -> AuthContext:
    if auth:
        if (auth.role_mask or 0) & (ROLE_ADMIN | ROLE_DEVELOPER):
            return auth
        raise HTTPException(403, "无权访问管理接口")
    header = request.headers.get("authorization", "")
    try:
        scheme, token = header.split(" ", 1)
        if scheme.lower() != "bearer":
            raise ValueError()
        claims = get_token_codec().decode(token)
        batch_id = int(request.path_params.get("batch_id", 0))
        if claims.get("kind") != "batch-admin" or not batch_id or claims.get("batchId") != batch_id:
            raise ValueError()
        user_id = int(claims["operatorId"])
        user, version = get_auth_repo().find_user_with_session_version(session, user_id)
        if not user or user.status != "active" or version != claims.get("sessionVersion"):
            raise ValueError()
        if not user.role_mask & (ROLE_ADMIN | ROLE_DEVELOPER):
            raise ValueError()
        action = "read" if request.method == "GET" else request.url.path.rsplit("/", 1)[-1]
        if action not in claims.get("permissions", []):
            raise ValueError()
        # Destructive review requests require a separate capability, checked by route.
        return AuthContext(user_id=user.id, role_mask=user.role_mask, source="batch-delegation", claims=dict(claims))
    except Exception as exc:
        raise HTTPException(403, "批次授权无效、已过期或权限不足") from exc
