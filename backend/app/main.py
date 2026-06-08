from __future__ import annotations

import logging
from contextlib import AsyncExitStack
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from app.api.deps import get_auth_service
from app.api.main import api_router
from app.core.config import get_settings
from app.core.db import prepare_database_runtime, session_scope
from app.core.exceptions import install_exception_handlers
from app.core.logging import bind_request_id, configure_logging, reset_request_id
from app.core.observability import get_runtime_metrics
from app.core.origin_guard import write_origin_allowed
from app.core.rate_limit import rate_limit_allowed
from app.core.response import api_fail
from app.core.security_headers import apply_security_headers
from app.mcp.auth import mcp_request_allowed
from app.mcp.server import create_studyhub_mcp


logger = logging.getLogger(__name__)


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


@asynccontextmanager
async def lifespan(app: FastAPI):
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
    mcp_server = getattr(app.state, "studyhub_mcp", None)
    if mcp_server is None:
        yield
    else:
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(mcp_server.session_manager.run())
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
    if settings.response_gzip_enabled:
        app.add_middleware(
            GZipMiddleware,
            minimum_size=max(256, settings.response_gzip_minimum_size_bytes),
            compresslevel=max(1, min(settings.response_gzip_compresslevel, 9)),
        )

    @app.middleware("http")
    async def record_http_observability(request: Request, call_next):
        started_at = perf_counter()
        request_id = request.headers.get("x-request-id") or uuid4().hex[:16]
        token = bind_request_id(request_id)
        response = None
        status_code = 500
        route_path = request.url.path

        def middleware_error_response(code: str, message: str, status: int) -> JSONResponse:
            error_response = JSONResponse(api_fail(code, message), status_code=status)
            error_response.headers["x-request-id"] = request_id
            apply_security_headers(settings, error_response.headers)
            return error_response

        try:
            rate_allowed, rate_error = rate_limit_allowed(settings, request)
            if not rate_allowed:
                status_code = 429
                response = middleware_error_response(
                    "RATE_LIMITED",
                    rate_error or "Too many requests",
                    status_code,
                )
                return response
            origin_allowed, origin_error = write_origin_allowed(settings, request)
            if not origin_allowed:
                status_code = 403
                response = middleware_error_response(
                    "ORIGIN_FORBIDDEN",
                    origin_error or "Write request origin is not allowed",
                    status_code,
                )
                return response
            mcp_allowed, mcp_error = (
                await mcp_request_allowed(settings, request)
                if route_path.startswith("/mcp")
                else (True, None)
            )
            if not mcp_allowed:
                status_code = 403
                response = middleware_error_response(
                    "MCP_FORBIDDEN",
                    mcp_error or "MCP request is not allowed",
                    status_code,
                )
                return response
            response = await call_next(request)
            status_code = response.status_code
            route = request.scope.get("route")
            route_path = getattr(route, "path", None) or route_path
            response.headers["x-request-id"] = request_id
            apply_security_headers(settings, response.headers)
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
            if route_path not in settings.resolved_access_log_skip_paths:
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
    if settings.resolved_mcp_enabled:
        studyhub_mcp = create_studyhub_mcp()
        app.state.studyhub_mcp = studyhub_mcp
        app.mount("/", studyhub_mcp.streamable_http_app())
    return app


app = create_app()
