from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.auth import AuthUser
from app.repos.auth_repo import AuthRepository
from app.repos.user_follow_repo import UserFollowRepository


class UserFollowService:
    def __init__(self, follow_repo: UserFollowRepository, auth_repo: AuthRepository) -> None:
        self.follow_repo = follow_repo
        self.auth_repo = auth_repo

    def follow(self, session: Session, *, follower_id: int, target_user_id: int) -> None:
        if follower_id == target_user_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能关注自己")
        self._require_user(session, follower_id)
        self._require_user(session, target_user_id)
        if self.follow_repo.exists_by_follower_and_following(session, follower_id, target_user_id):
            return
        self.follow_repo.create(session, follower_id=follower_id, following_id=target_user_id)
        session.commit()

    def unfollow(self, session: Session, *, follower_id: int, target_user_id: int) -> None:
        self._require_user(session, follower_id)
        self._require_user(session, target_user_id)
        entity = self.follow_repo.find_by_follower_and_following(session, follower_id, target_user_id)
        if entity is None:
            return
        self.follow_repo.delete(session, entity)
        session.commit()

    def list_followers(self, session: Session, target_user_id: int) -> list[dict[str, object]]:
        self._require_user(session, target_user_id)
        return [self._to_follow_item(user) for user in self.follow_repo.list_followers(session, target_user_id)]

    def list_following(self, session: Session, target_user_id: int) -> list[dict[str, object]]:
        self._require_user(session, target_user_id)
        return [self._to_follow_item(user) for user in self.follow_repo.list_following(session, target_user_id)]

    def is_following(self, session: Session, *, follower_id: int | None, target_user_id: int) -> bool:
        if follower_id is None or follower_id == target_user_id:
            return False
        return self.follow_repo.exists_by_follower_and_following(session, follower_id, target_user_id)

    def count_followers(self, session: Session, user_id: int) -> int:
        return self.follow_repo.count_followers(session, user_id)

    def count_following(self, session: Session, user_id: int) -> int:
        return self.follow_repo.count_following(session, user_id)

    def _require_user(self, session: Session, user_id: int) -> AuthUser:
        user = self.auth_repo.find_user_by_id(session, user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
        return user

    def _to_follow_item(self, user: AuthUser) -> dict[str, object]:
        return {
            "id": user.id,
            "username": user.username,
            "nickname": user.nickname or user.username,
            "signature": user.signature,
            "school": user.school,
            "college": user.college,
            "major": user.major,
            "avatar": user.avatar,
        }
