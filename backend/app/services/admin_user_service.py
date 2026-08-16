from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.admin import UserNoteRecord
from app.repos.admin_repo import AdminRepository
from app.repos.auth_repo import AuthRepository, AuthUserModel, resolve_user_model
from app.repos.read_api_repo import ReadApiRepository
from app.schemas.admin import AdminCreateUserNotePayload, AdminCreateUserPayload
from app.services.auth_service import AuthService
from app.services.read_support import ROLE_DEVELOPER, has_role, serialize_datetime


class AdminUserService:
    def __init__(
        self,
        read_repo: ReadApiRepository,
        admin_repo: AdminRepository,
        auth_repo: AuthRepository,
        auth_service: AuthService,
    ) -> None:
        self.read_repo = read_repo
        self.admin_repo = admin_repo
        self.auth_repo = auth_repo
        self.auth_service = auth_service

    def list_users(self, session: Session, *, keyword: str | None) -> list[dict[str, Any]]:
        user_model = resolve_user_model(session)
        stmt = select(user_model).order_by(user_model.created_at.desc(), user_model.id.desc())
        if keyword:
            normalized = keyword.strip().lower()
            if normalized:
                pattern = f"%{_escape_like(normalized)}%"
                stmt = stmt.where(
                    or_(
                        func.lower(user_model.username).like(pattern, escape="\\"),
                        func.lower(user_model.nickname).like(pattern, escape="\\"),
                    )
                )
        users = list(session.scalars(stmt.limit(200)))
        seed = self.read_repo.load_seed()
        return [self._to_summary(user, seed=seed) for user in users]

    def create_user(self, session: Session, payload: AdminCreateUserPayload, *, operator_role_mask: int | None) -> dict[str, Any]:
        desired_role_mask = int(payload.roleMask or 1)
        self._ensure_role_grant_allowed(operator_role_mask, desired_role_mask)
        user = self.auth_service.create_local_user(
            session,
            username=payload.username,
            password=payload.password,
            nickname=payload.nickname,
            verified=True,
        )
        user.role_mask = desired_role_mask
        self.auth_repo.save_user(session, user)
        session.commit()
        return self._to_summary(user)

    def update_roles(self, session: Session, user_id: int, role_mask: int, *, operator_role_mask: int | None) -> dict[str, Any]:
        self._ensure_role_grant_allowed(operator_role_mask, role_mask)
        user = self.auth_repo.find_user_by_id(session, user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
        user.role_mask = role_mask
        self.auth_repo.save_user(session, user)
        self.auth_repo.bump_session_version(session, user.id, reason="roles_changed")
        session.commit()
        return self._to_summary(user)

    def list_notes(self, session: Session, user_id: int) -> list[dict[str, Any]]:
        self._require_user(session, user_id)
        seed = self.read_repo.load_seed()
        seed_notes = list(((seed.get("profileSummary") or {}).get(str(user_id), {}) or {}).get("adminNotes") or [])
        db_notes = [self._to_note(entity, session) for entity in self.admin_repo.list_notes_by_user(session, user_id)]
        return db_notes + seed_notes

    def create_note(self, session: Session, user_id: int, admin_user_id: int, payload: AdminCreateUserNotePayload) -> dict[str, Any]:
        self._require_user(session, user_id)
        admin = self._require_user(session, admin_user_id, label="管理员")
        entity = UserNoteRecord(
            user_id=user_id,
            admin_user_id=admin.id,
            message=payload.message.strip(),
        )
        self.admin_repo.save_note(session, entity)
        session.commit()
        return self._to_note(entity, session)

    def _ensure_role_grant_allowed(self, operator_role_mask: int | None, desired_role_mask: int) -> None:
        wants_developer = has_role(desired_role_mask, ROLE_DEVELOPER)
        if wants_developer and not has_role(operator_role_mask, ROLE_DEVELOPER):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅超级管理员可以创建或授权超级管理员账号")

    def _require_user(self, session: Session, user_id: int, *, label: str = "用户") -> AuthUserModel:
        user = self.auth_repo.find_user_by_id(session, user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{label}不存在")
        return user

    def _to_summary(self, user: AuthUserModel, *, seed: dict[str, Any] | None = None) -> dict[str, Any]:
        if seed is None:
            seed = self.read_repo.load_seed()
        total_earnings = float((((seed.get("profileSummary") or {}).get(str(user.id), {}) or {}).get("totals") or {}).get("totalEarnings", 0))
        return {
            "id": user.id,
            "username": user.username,
            "nickname": user.nickname,
            "roleMask": user.role_mask,
            "createdAt": serialize_datetime(user.created_at),
            "updatedAt": serialize_datetime(user.updated_at),
            "totalEarnings": total_earnings,
        }

    def _to_note(self, entity: UserNoteRecord, session: Session) -> dict[str, Any]:
        admin = self.auth_repo.find_user_by_id(session, entity.admin_user_id)
        return {
            "id": entity.id,
            "adminId": entity.admin_user_id,
            "adminUsername": admin.username if admin else None,
            "adminNickname": admin.nickname if admin else None,
            "message": entity.message,
            "createdAt": serialize_datetime(entity.created_at),
        }


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
