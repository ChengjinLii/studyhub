from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import (
    get_admin_user_service,
    get_materials_service,
    get_public_read_cache,
    require_auth_context,
    require_privileged_auth_context,
)
from app.core.db import get_db_session
from app.core.public_read_cache import invalidate_prefixes
from app.core.response import api_ok
from app.core.security import AuthContext
from app.schemas.admin import (
    AdminCreateUserNotePayload,
    AdminCreateUserPayload,
    AdminMaterialBatchDeletePayload,
    AdminMaterialStatusPayload,
    AdminMaterialBatchUpdatePayload,
    AdminUpdateRolePayload,
)
from app.services.admin_user_service import AdminUserService
from app.services.materials_service import MaterialsService


router = APIRouter(tags=["admin"])


@router.get("/api/admin/users")
def list_users(
    keyword: str | None = None,
    _: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: AdminUserService = Depends(get_admin_user_service),
) -> dict[str, object]:
    return api_ok(service.list_users(session, keyword=keyword))


@router.post("/api/admin/users")
def create_user(
    payload: AdminCreateUserPayload,
    auth: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: AdminUserService = Depends(get_admin_user_service),
) -> dict[str, object]:
    return api_ok(service.create_user(session, payload, operator_role_mask=auth.role_mask))


@router.patch("/api/admin/users", include_in_schema=False)
def update_user_roles_alias(
    payload: AdminUpdateRolePayload,
    id: int = Query(..., ge=1),
    auth: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: AdminUserService = Depends(get_admin_user_service),
) -> dict[str, object]:
    return api_ok(service.update_roles(session, id, payload.roleMask, operator_role_mask=auth.role_mask))


@router.patch("/api/admin/users/{id}/roles")
@router.patch("/api/admin/users/{id}")
def update_user_roles(
    id: int,
    payload: AdminUpdateRolePayload,
    auth: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: AdminUserService = Depends(get_admin_user_service),
) -> dict[str, object]:
    return api_ok(service.update_roles(session, id, payload.roleMask, operator_role_mask=auth.role_mask))


@router.get("/api/admin/user-notes", include_in_schema=False)
def list_user_notes_alias(
    userId: int = Query(..., ge=1),
    _: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: AdminUserService = Depends(get_admin_user_service),
) -> dict[str, object]:
    return api_ok(service.list_notes(session, userId))


@router.post("/api/admin/user-notes", include_in_schema=False)
def create_user_note_alias(
    payload: AdminCreateUserNotePayload,
    userId: int = Query(..., ge=1),
    auth: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: AdminUserService = Depends(get_admin_user_service),
) -> dict[str, object]:
    return api_ok(service.create_note(session, userId, auth.user_id or 0, payload))


@router.get("/api/admin/users/{id}/notes")
def list_user_notes(
    id: int,
    _: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: AdminUserService = Depends(get_admin_user_service),
) -> dict[str, object]:
    return api_ok(service.list_notes(session, id))


@router.post("/api/admin/users/{id}/notes")
def create_user_note(
    id: int,
    payload: AdminCreateUserNotePayload,
    auth: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: AdminUserService = Depends(get_admin_user_service),
) -> dict[str, object]:
    return api_ok(service.create_note(session, id, auth.user_id or 0, payload))


@router.get("/api/admin/materials")
def list_materials_for_admin(
    page: int = 0,
    size: int = 20,
    status: str | None = None,
    _: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: MaterialsService = Depends(get_materials_service),
) -> dict[str, object]:
    return api_ok(service.list_for_admin(session, page=page, size=size, status_value=status))


@router.delete("/api/admin/materials/{id}")
def delete_material_for_admin(
    id: int,
    _: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: MaterialsService = Depends(get_materials_service),
) -> dict[str, object]:
    service.delete_material(session, id, operator_id=0, can_manage_all=True)
    _invalidate_admin_material_read_caches()
    return api_ok()


@router.post("/api/admin/materials/{id}/restore", include_in_schema=False)
@router.put("/api/admin/materials/{id}/restoration")
def restore_material_for_admin(
    id: int,
    _: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: MaterialsService = Depends(get_materials_service),
) -> dict[str, object]:
    service.restore_material(session, id, can_manage_all=True)
    _invalidate_admin_material_read_caches()
    return api_ok()


@router.patch("/api/admin/materials/{id}")
def update_material_status_for_admin(
    id: int,
    payload: AdminMaterialStatusPayload,
    _: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: MaterialsService = Depends(get_materials_service),
) -> dict[str, object]:
    service.restore_material(session, id, can_manage_all=True)
    _invalidate_admin_material_read_caches()
    return api_ok()


@router.post("/api/admin/materials/batch-update", include_in_schema=False)
@router.patch("/api/admin/materials")
def batch_update_materials_for_admin(
    payload: AdminMaterialBatchUpdatePayload,
    _: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: MaterialsService = Depends(get_materials_service),
) -> dict[str, object]:
    data = service.batch_update_materials(session, payload)
    _invalidate_admin_material_read_caches()
    return api_ok(data)


@router.post("/api/admin/materials/batch-delete", include_in_schema=False)
@router.delete("/api/admin/materials")
def batch_delete_materials_for_admin(
    payload: AdminMaterialBatchDeletePayload,
    _: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: MaterialsService = Depends(get_materials_service),
) -> dict[str, object]:
    data = service.batch_delete_materials(session, payload.materialIds)
    _invalidate_admin_material_read_caches()
    return api_ok(data)


@router.post("/api/admin/materials/batch-restore", include_in_schema=False)
@router.post("/api/admin/material-restorations")
def batch_restore_materials_for_admin(
    payload: AdminMaterialBatchDeletePayload,
    _: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: MaterialsService = Depends(get_materials_service),
) -> dict[str, object]:
    data = service.batch_restore_materials(session, payload.materialIds)
    _invalidate_admin_material_read_caches()
    return api_ok(data)


def _invalidate_admin_material_read_caches() -> None:
    invalidate_prefixes(get_public_read_cache(), "materials", "leaderboard")
