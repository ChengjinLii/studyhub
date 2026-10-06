from __future__ import annotations

import asyncio
import hmac
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Receive, Scope, Send

from . import __version__
from .backends import AutoBackend
from .config import Settings
from .media import InvalidImage
from .schemas import ReviewRequest, ReviewResponse
from .service import ReviewService

MAX_BODY_BYTES = 24 * 1024 * 1024


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp, limit: int = MAX_BODY_BYTES):
        self.app, self.limit = app, limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http" or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        if headers.get(b"content-encoding", b"identity") != b"identity":
            response = JSONResponse(
                status_code=415, content={"detail": "compressed bodies unsupported"}
            )
            return await response(scope, receive, send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > self.limit:
                response = JSONResponse(
                    status_code=413, content={"detail": "request body too large"}
                )
                return await response(scope, receive, send)
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)
        delivered = False

        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)


def create_app(service: ReviewService | None = None, settings: Settings | None = None) -> FastAPI:
    service = service or ReviewService(settings)
    settings = service.settings
    capacity = asyncio.Semaphore(settings.max_concurrent_reviews)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        service.close()

    app = FastAPI(title="StudyHub Review-Jev", version=__version__, lifespan=lifespan)
    app.add_middleware(BodyLimitMiddleware)
    app.state.review_service = service

    async def authenticate(request: Request):
        if settings.api_key and not hmac.compare_digest(
            request.headers.get("authorization", "").encode("utf-8"),
            f"Bearer {settings.api_key}".encode("utf-8"),
        ):
            raise HTTPException(status_code=401, detail="invalid API key")

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # Pydantic's input/context can contain full submissions or base64 images.
        detail = [
            {"loc": item["loc"], "msg": item["msg"], "type": item["type"]} for item in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": detail})

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "service": "review-jev",
            "version": __version__,
            "backend": service.backend.name,
            "demo": service.backend.demo,
        }

    @app.get("/ready", dependencies=[Depends(authenticate)])
    def readiness():
        ready = service.backend.ready()
        details = {}
        if isinstance(service.backend, AutoBackend):
            details = {
                "text": service.backend.text.ready(),
                "images": service.backend.images.ready(),
                "large": service.backend.large.ready(),
            }
        return JSONResponse(
            status_code=200 if ready else 503,
            content={
                "status": "ready" if ready else "not_ready",
                "demo": service.backend.demo,
                "backends": details,
            },
        )

    @app.get("/v1/policy", dependencies=[Depends(authenticate)])
    def policy():
        return {
            **service.policy.model_dump(),
            "calibrated_for_studyhub": False,
            "allow_auto_approve": settings.allow_auto_approve,
            "allow_auto_reject": settings.allow_auto_reject,
            "routing": {
                "backend": settings.backend,
                "text_model": settings.text_model if settings.backend == "auto" else settings.model,
                "image_model": settings.model if settings.backend == "auto" else None,
                "text_custom_policy_applied": settings.backend not in {"auto", "qwen3guard"},
                "cascade_enabled": settings.backend == "auto" and settings.cascade_enabled,
                "large_model": settings.large_model if settings.backend == "auto" else None,
                "confidence_thresholds": {
                    "0.6b": settings.text_confidence_threshold,
                    "4b": settings.image_confidence_threshold,
                    "9b": settings.large_confidence_threshold,
                },
            },
        }

    @app.post("/v1/reviews", response_model=ReviewResponse, dependencies=[Depends(authenticate)])
    async def review(body: ReviewRequest):
        try:
            await asyncio.wait_for(capacity.acquire(), timeout=0.05)
        except asyncio.TimeoutError as exc:
            raise HTTPException(
                status_code=503, detail="review capacity exceeded; retry later"
            ) from exc
        try:
            return await run_in_threadpool(service.review, body)
        except InvalidImage as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            capacity.release()

    return app
