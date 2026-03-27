from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.deps import get_auth_service
from app.api.main import api_router
from app.core.config import get_settings
from app.core.db import prepare_database_runtime, session_scope
from app.core.exceptions import install_exception_handlers
from app.core.logging import bind_request_id, configure_logging, reset_request_id
from app.core.observability import get_runtime_metrics


logger = logging.getLogger(__name__)
_LOCAL_API_PATHS = {"/api/healthz", "/api/readyz", "/api/metrics", "/healthz", "/readyz", "/metrics"}
_LOCAL_PREVIEW_DIRECT_API_ROUTES = (
    ("GET", re.compile(r"^/api/materials$")),
    ("GET", re.compile(r"^/api/materials/recommendations$")),
    ("GET", re.compile(r"^/api/materials/\d+$")),
    ("GET", re.compile(r"^/api/leaderboard/contributors$")),
    ("GET", re.compile(r"^/api/market$")),
    ("GET", re.compile(r"^/api/market/\d+$")),
    ("GET", re.compile(r"^/api/requests$")),
    ("GET", re.compile(r"^/api/requests/leaderboard$")),
    ("GET", re.compile(r"^/api/requests/\d+$")),
    ("GET", re.compile(r"^/api/requests/\d+/responses$")),
    ("GET", re.compile(r"^/api/requests/\d+/contributions$")),
    ("GET", re.compile(r"^/api/comments$")),
    ("GET", re.compile(r"^/api/comments/\d+/replies$")),
)
_HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-length",
}


def _ensure_runtime_directories() -> None:
    settings = get_settings()
    if settings.is_local_dev:
        settings.local_dev_root.mkdir(parents=True, exist_ok=True)
    elif settings.requires_private_env_file:
        settings.private_dir.mkdir(parents=True, exist_ok=True)
    settings.resolved_contract_report_dir.mkdir(parents=True, exist_ok=True)
    if settings.storage_provider == "local_fs":
        settings.resolved_material_asset_dir.mkdir(parents=True, exist_ok=True)
        settings.resolved_market_asset_dir.mkdir(parents=True, exist_ok=True)
        settings.resolved_payout_qr_asset_dir.mkdir(parents=True, exist_ok=True)
    if settings.mail_provider == "local_outbox":
        settings.resolved_mail_outbox_dir.mkdir(parents=True, exist_ok=True)


def _should_proxy_api_request(settings, request: Request) -> bool:
    if not settings.legacy_api_proxy_enabled:
        return False
    path = request.url.path
    if not path.startswith("/api/") or path in _LOCAL_API_PATHS:
        return False
    method = request.method.upper()
    for allowed_method, pattern in _LOCAL_PREVIEW_DIRECT_API_ROUTES:
        if method == allowed_method and pattern.match(path):
            return False
    return True


async def _proxy_api_request(settings, request: Request) -> Response:
    upstream_base = (settings.legacy_api_proxy_base_url or "").rstrip("/")
    upstream_url = f"{upstream_base}{request.url.path}"
    if request.url.query:
        upstream_url = f"{upstream_url}?{request.url.query}"

    forwarded_headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in {"host", "content-length"}
    }
    body = await request.body()
    timeout = httpx.Timeout(connect=5.0, read=60.0, write=60.0, pool=5.0)
    async with httpx.AsyncClient(follow_redirects=False, timeout=timeout) as client:
        upstream_response = await client.request(
            request.method,
            upstream_url,
            content=body,
            headers=forwarded_headers,
            cookies=request.cookies,
        )

    response = Response(content=upstream_response.content, status_code=upstream_response.status_code)
    for key, value in upstream_response.headers.items():
        lower_key = key.lower()
        if lower_key in _HOP_BY_HOP_HEADERS or lower_key == "set-cookie":
            continue
        response.headers[key] = value
    for cookie_header in upstream_response.headers.get_list("set-cookie"):
        response.headers.append("set-cookie", cookie_header)
    response.headers["x-studyhub-preview-upstream"] = "legacy-java"
    return response


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level, log_format=settings.log_format, access_log_enabled=settings.access_log_enabled)
    _ensure_runtime_directories()
    prepare_database_runtime()
    if settings.is_local_dev and settings.local_dev_bootstrap_user:
        local_dev_identity: tuple[str, int] | None = None
        with session_scope() as session:
            local_dev_user = get_auth_service().ensure_local_dev_user(session)
            if local_dev_user is not None:
                local_dev_identity = (local_dev_user.username, local_dev_user.id)
        if local_dev_identity is not None:
            logger.info("Local-dev developer account ready: %s#%s", local_dev_identity[0], local_dev_identity[1])
    logger.info("Application booted on %s:%s in %s", settings.host, settings.port, settings.environment)
    yield
    logger.info("Application shutdown complete")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )
    if settings.resolved_cors_allowed_origins or settings.resolved_cors_allow_origin_regex:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.resolved_cors_allowed_origins,
            allow_origin_regex=settings.resolved_cors_allow_origin_regex,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.middleware("http")
    async def record_http_observability(request: Request, call_next):
        started_at = perf_counter()
        request_id = request.headers.get("x-request-id") or uuid4().hex[:16]
        token = bind_request_id(request_id)
        response = None
        status_code = 500
        route_path = request.url.path
        try:
            if _should_proxy_api_request(settings, request):
                response = await _proxy_api_request(settings, request)
                route_path = f"legacy-proxy:{request.url.path}"
            else:
                response = await call_next(request)
            status_code = response.status_code
            route = request.scope.get("route")
            route_path = getattr(route, "path", None) or route_path
            response.headers["x-request-id"] = request_id
            return response
        finally:
            duration_seconds = perf_counter() - started_at
            duration_ms = round(duration_seconds * 1000, 2)
            get_runtime_metrics().record_http_request(
                method=request.method,
                route=route_path,
                status_code=status_code,
                duration_seconds=duration_seconds,
            )
            log_level = logging.ERROR if status_code >= 500 else logging.INFO
            logger.log(
                log_level,
                "HTTP request completed",
                extra={
                    "event": "http_request",
                    "environment": settings.environment,
                    "method": request.method,
                    "path": route_path,
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                    "client_ip": request.client.host if request.client else None,
                },
            )
            reset_request_id(token)

    install_exception_handlers(app)
    app.include_router(api_router)
    return app


app = create_app()
