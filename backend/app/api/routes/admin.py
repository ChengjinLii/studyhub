from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import (
    get_admin_user_service,
    get_materials_service,
    require_auth_context,
    require_privileged_auth_context,
)
from app.core.db import get_db_session
from app.core.response import api_ok
from app.core.security import AuthContext
from app.schemas.admin import (
    AdminCreateUserNotePayload,
    AdminCreateUserPayload,
    AdminMaterialBatchDeletePayload,
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


@router.patch("/api/admin/users")
def update_user_roles_alias(
    payload: AdminUpdateRolePayload,
    id: int = Query(..., ge=1),
    auth: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: AdminUserService = Depends(get_admin_user_service),
) -> dict[str, object]:
    return api_ok(service.update_roles(session, id, payload.roleMask, operator_role_mask=auth.role_mask))


@router.patch("/api/admin/users/{id}/roles")
def update_user_roles(
    id: int,
    payload: AdminUpdateRolePayload,
    auth: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: AdminUserService = Depends(get_admin_user_service),
) -> dict[str, object]:
    return api_ok(service.update_roles(session, id, payload.roleMask, operator_role_mask=auth.role_mask))


@router.get("/api/admin/user-notes")
def list_user_notes_alias(
    userId: int = Query(..., ge=1),
    _: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: AdminUserService = Depends(get_admin_user_service),
) -> dict[str, object]:
    return api_ok(service.list_notes(session, userId))


@router.post("/api/admin/user-notes")
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
    return api_ok()


@router.post("/api/admin/materials/{id}/restore")
def restore_material_for_admin(
    id: int,
    _: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: MaterialsService = Depends(get_materials_service),
) -> dict[str, object]:
    service.restore_material(session, id, can_manage_all=True)
    return api_ok()


@router.post("/api/admin/materials/batch-update")
def batch_update_materials_for_admin(
    payload: AdminMaterialBatchUpdatePayload,
    _: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: MaterialsService = Depends(get_materials_service),
) -> dict[str, object]:
    return api_ok(service.batch_update_materials(session, payload))


@router.post("/api/admin/materials/batch-delete")
def batch_delete_materials_for_admin(
    payload: AdminMaterialBatchDeletePayload,
    _: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: MaterialsService = Depends(get_materials_service),
) -> dict[str, object]:
    return api_ok(service.batch_delete_materials(session, payload.materialIds))


@router.post("/api/admin/materials/batch-restore")
def batch_restore_materials_for_admin(
    payload: AdminMaterialBatchDeletePayload,
    _: AuthContext = Depends(require_privileged_auth_context),
    session: Session = Depends(get_db_session),
    service: MaterialsService = Depends(get_materials_service),
) -> dict[str, object]:
    return api_ok(service.batch_restore_materials(session, payload.materialIds))
