from __future__ import annotations

from pathlib import Path
import tempfile

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.formparsers import MultiPartException, MultiPartParser
from starlette.datastructures import UploadFile

from app.api.deps import (
    get_auth_repo,
    get_token_codec,
    get_material_asset_store,
    get_materials_service,
    get_public_read_cache,
    get_upload_authorization_service,
    require_auth_context,
    require_privileged_auth_context,
)
from app.api.batch_access import require_batch_admin
from app.core.config import get_settings
from app.core.db import get_db_session
from app.core.public_read_cache import invalidate_prefixes
from app.core.response import api_ok
from app.core.security import AuthContext
from app.schemas.batch_submissions import BatchAccessPayload, BatchAmendPayload, BatchCreatePayload, BatchPublishPayload, BatchReviewPayload
from app.services.batch_submission_service import BatchSubmissionService


def private_response(response: Response):
    response.headers["Cache-Control"] = "private, no-store"


router = APIRouter(tags=["batch-submissions"], dependencies=[Depends(private_response)])


def get_batch_submission_service() -> BatchSubmissionService:
    return BatchSubmissionService(
        get_settings(), get_material_asset_store(), get_materials_service(), get_upload_authorization_service()
    )


@router.post("/api/batch-submissions")
def create_batch(
    payload: BatchCreatePayload,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: BatchSubmissionService = Depends(get_batch_submission_service),
):
    return api_ok(service.create(session, user_id=auth.user_id, payload=payload.model_dump()))


@router.get("/api/batch-submissions")
def own_batches(
    offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=50),
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: BatchSubmissionService = Depends(get_batch_submission_service),
):
    return api_ok(service.list_batches(session, user_id=auth.user_id, offset=offset, limit=limit))


@router.get("/api/batch-submissions/{batch_id}")
def own_batch(
    batch_id: int,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: BatchSubmissionService = Depends(get_batch_submission_service),
):
    return api_ok(service.detail(session, batch_id, user_id=auth.user_id))


@router.post("/api/batch-submissions/{batch_id}/items/{item_id}/authorize")
def authorize_file(
    batch_id: int, item_id: int,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: BatchSubmissionService = Depends(get_batch_submission_service),
):
    return api_ok(service.authorize_upload(session, batch_id, item_id, user_id=auth.user_id))


@router.patch("/api/batch-submissions/{batch_id}")
def amend_batch(
    batch_id: int, payload: BatchAmendPayload,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: BatchSubmissionService = Depends(get_batch_submission_service),
):
    return api_ok(service.amend(
        session, batch_id, user_id=auth.user_id, payload=payload.model_dump(exclude_none=True)
    ))


@router.put("/api/batch-submissions/{batch_id}/items/{item_id}/file")
async def upload_file(
    batch_id: int, item_id: int, request: Request,
    x_studyhub_upload_token: str = Header(default=""),
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: BatchSubmissionService = Depends(get_batch_submission_service),
):
    completed = await run_in_threadpool(service.begin_upload, session, batch_id, item_id,
                                        user_id=auth.user_id, token=x_studyhub_upload_token)
    if completed:
        return api_ok({"id": item_id, "status": "UPLOADED"})
    async def limited_stream():
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > 51 * 1024 * 1024:
                raise HTTPException(413, "单个文件不能超过 50MB")
            yield chunk

    parser = MultiPartParser(request.headers, limited_stream(), max_files=1, max_fields=0)
    try:
        form = await parser.parse()
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            raise HTTPException(400, "请选择文件")
        return api_ok(await run_in_threadpool(
            service.upload, session, batch_id, item_id,
            user_id=auth.user_id, token=x_studyhub_upload_token, upload=upload,
        ))
    except MultiPartException as exc:
        raise HTTPException(400, "上传格式不正确，每次只能上传一个文件") from exc
    finally:
        # Includes parser failures and request cancellation before FormData exists.
        for temporary in parser._files_to_close_on_error:
            temporary.close()
        await run_in_threadpool(service.release_receive, session, batch_id, item_id, token=x_studyhub_upload_token)


@router.post("/api/batch-submissions/{batch_id}/submit")
def submit_batch(
    batch_id: int,
    auth: AuthContext = Depends(require_auth_context),
    session: Session = Depends(get_db_session),
    service: BatchSubmissionService = Depends(get_batch_submission_service),
):
    return api_ok(service.submit(session, batch_id, user_id=auth.user_id))


@router.get("/api/admin/batch-submissions")
def admin_batches(
    offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=50),
    _: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: BatchSubmissionService = Depends(get_batch_submission_service),
):
    return api_ok(service.list_batches(session, offset=offset, limit=limit))


@router.get("/api/admin/batch-submissions/{batch_id}")
def admin_batch(
    batch_id: int,
    _: AuthContext = Depends(require_batch_admin),
    session: Session = Depends(get_db_session),
    service: BatchSubmissionService = Depends(get_batch_submission_service),
):
    return api_ok(service.detail(session, batch_id))


@router.post("/api/admin/batch-submissions/{batch_id}/access-token")
def issue_batch_access(
    batch_id: int, payload: BatchAccessPayload,
    auth: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: BatchSubmissionService = Depends(get_batch_submission_service),
):
    service.detail(session, batch_id)
    token = get_token_codec().encode({
        "sub": f"batch-admin:{auth.user_id}", "kind": "batch-admin", "operatorId": auth.user_id,
        "batchId": batch_id, "permissions": payload.permissions,
        "sessionVersion": get_auth_repo().get_session_version(session, auth.user_id),
    }, ttl_seconds=900)
    return api_ok({"token": token, "expiresInSeconds": 900, "batchId": batch_id, "permissions": payload.permissions})


@router.post("/api/admin/batch-submissions/{batch_id}/review")
def review_batch(
    batch_id: int, payload: BatchReviewPayload,
    auth: AuthContext = Depends(require_batch_admin),
    session: Session = Depends(get_db_session),
    service: BatchSubmissionService = Depends(get_batch_submission_service),
):
    if auth.source == "batch-delegation" and payload.action == "REJECT" and "cleanup" not in auth.claims.get("permissions", []):
        raise HTTPException(403, "此授权不允许拒收清理")
    return api_ok(service.review(session, batch_id, operator_id=auth.user_id, payload=payload.model_dump()))


@router.post("/api/admin/batch-submissions/{batch_id}/publish")
def publish_batch(
    batch_id: int, payload: BatchPublishPayload,
    auth: AuthContext = Depends(require_batch_admin),
    session: Session = Depends(get_db_session),
    service: BatchSubmissionService = Depends(get_batch_submission_service),
):
    result = service.publish(session, batch_id, operator_id=auth.user_id, payload=payload.model_dump())
    invalidate_prefixes(get_public_read_cache(), "materials", "home", "leaderboard")
    return api_ok(result)


@router.get("/api/admin/batch-submissions/{batch_id}/items/{item_id}/download")
def download_link(
    batch_id: int, item_id: int,
    _: AuthContext = Depends(require_batch_admin),
    session: Session = Depends(get_db_session),
    service: BatchSubmissionService = Depends(get_batch_submission_service),
):
    service.download_item(session, batch_id, item_id)
    # download_item only reads (via SELECT ... FOR UPDATE guards against a
    # concurrent status change while we look). Release those row locks
    # immediately instead of holding them until the dependency tears down the
    # session at the end of the request.
    session.commit()
    return api_ok({"url": f"/api/admin/batch-submissions/{batch_id}/items/{item_id}/file"})


@router.get("/api/admin/batch-submissions/{batch_id}/items/{item_id}/file")
def download_file(
    batch_id: int, item_id: int,
    _: AuthContext = Depends(require_batch_admin),
    session: Session = Depends(get_db_session),
    service: BatchSubmissionService = Depends(get_batch_submission_service),
):
    item = service.download_item(session, batch_id, item_id)
    object_key, filename = item.object_key, item.name
    # Release the batch/item FOR UPDATE locks taken by download_item before
    # doing the (potentially slow, network-bound) object storage copy below.
    # Without this, the row locks stay held for the full OSS transfer time,
    # blocking any concurrent admin action on the same batch/item.
    session.commit()
    with tempfile.NamedTemporaryFile(prefix="studyhub-batch-", delete=False) as output:
        path = Path(output.name)
    try:
        service.asset_store.copy_to_path(object_key, path, max_size_bytes=50 * 1024 * 1024)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return FileResponse(
        path, filename=filename, media_type="application/octet-stream",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
        background=BackgroundTask(path.unlink, missing_ok=True),
    )
