from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.profile_metadata import (
    normalize_college_selection,
    normalize_grade_stages,
    normalize_major_selection,
    normalize_school_selection,
)
from app.models.auth import AuthUser
from app.repos.auth_repo import AuthRepository
from app.repos.read_api_repo import ReadApiRepository
from app.schemas.account import AccountProfilePayload, AccountUpdateRequestPayload
from app.services.read_support import serialize_user_snapshot


class AccountService:
    def __init__(self, repo: AuthRepository, read_repo: ReadApiRepository) -> None:
        self.repo = repo
        self.read_repo = read_repo

    def get_account(self, session: Session, user_id: int) -> AccountProfilePayload:
        user = self.repo.find_user_by_id(session, user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
        return self._to_payload(user)

    def update_account(self, session: Session, user_id: int, payload: AccountUpdateRequestPayload) -> AuthUser:
        user = self.repo.find_user_by_id(session, user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

        if payload.nickname is not None:
            normalized = payload.nickname.strip()
            user.nickname = normalized or user.username
        if payload.emailPrivacy is not None:
            user.email_privacy = payload.emailPrivacy
        if payload.signature is not None:
            normalized = payload.signature.strip()
            user.signature = normalized or None
        if payload.school is not None:
            normalized = normalize_school_selection(payload.school)
            user.school = normalized
            if normalized is None:
                user.college = None
                user.major = None
        if payload.college is not None:
            user.college = normalize_college_selection(payload.college)
        if payload.major is not None:
            user.major = normalize_major_selection(payload.major)
        if payload.gradeStages is not None:
            user.grade_stages = normalize_grade_stages(payload.gradeStages)

        self.repo.save_user(session, user)
        session.commit()
        session.refresh(user)
        return user

    def to_payload(self, user: AuthUser) -> AccountProfilePayload:
        return self._to_payload(user)

    def _to_payload(self, user: AuthUser) -> AccountProfilePayload:
        seed = self.read_repo.load_seed()
        snapshot = self._resolve_snapshot(user, seed)
        return AccountProfilePayload(
            id=user.id,
            username=user.username,
            nickname=snapshot.get("nickname") or user.username,
            signature=snapshot.get("signature"),
            school=snapshot.get("school"),
            college=snapshot.get("college"),
            major=snapshot.get("major"),
            gradeStages=list(snapshot.get("gradeStages") or []),
            email=snapshot.get("email"),
            emailPrivacy=bool(snapshot.get("emailPrivacy")),
            avatar=snapshot.get("avatar"),
            payoutQrUrl=snapshot.get("payoutQrUrl"),
            legendaryContributorUntil=snapshot.get("legendaryContributorUntil"),
            purchaseCount=self._purchase_count(seed, user.id),
            saleCount=self._sale_count(seed, user.id),
        )

    def _resolve_snapshot(self, user: AuthUser, seed: dict[str, Any]) -> dict[str, object]:
        seed_user = (seed.get("users") or {}).get(str(user.id))
        return serialize_user_snapshot(seed_user, user)

    def _purchase_count(self, seed: dict[str, Any], user_id: int) -> int:
        purchases = (seed.get("profileSummary") or {}).get(str(user_id), {}).get("purchases", [])
        return len(purchases)

    def _sale_count(self, seed: dict[str, Any], user_id: int) -> int:
        return sum(
            1
            for material in seed.get("materials", [])
            if int(material.get("uploaderId", 0)) == user_id and not bool(material.get("free"))
        )
