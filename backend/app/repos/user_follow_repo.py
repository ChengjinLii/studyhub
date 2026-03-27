from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.auth import AuthUser
from app.models.social import UserFollow


class UserFollowRepository:
    def exists_by_follower_and_following(self, session: Session, follower_id: int, following_id: int) -> bool:
        stmt = select(UserFollow.id).where(
            UserFollow.follower_id == follower_id,
            UserFollow.following_id == following_id,
        )
        return session.scalar(stmt) is not None

    def find_by_follower_and_following(self, session: Session, follower_id: int, following_id: int) -> UserFollow | None:
        stmt = select(UserFollow).where(
            UserFollow.follower_id == follower_id,
            UserFollow.following_id == following_id,
        )
        return session.scalar(stmt)

    def create(self, session: Session, *, follower_id: int, following_id: int) -> UserFollow:
        entity = UserFollow(follower_id=follower_id, following_id=following_id)
        session.add(entity)
        session.flush()
        session.refresh(entity)
        return entity

    def delete(self, session: Session, entity: UserFollow) -> None:
        session.delete(entity)

    def delete_by_pair(self, session: Session, *, follower_id: int, following_id: int) -> None:
        stmt = delete(UserFollow).where(
            UserFollow.follower_id == follower_id,
            UserFollow.following_id == following_id,
        )
        session.execute(stmt)

    def count_followers(self, session: Session, user_id: int) -> int:
        stmt = select(func.count(UserFollow.id)).where(UserFollow.following_id == user_id)
        return int(session.scalar(stmt) or 0)

    def count_following(self, session: Session, user_id: int) -> int:
        stmt = select(func.count(UserFollow.id)).where(UserFollow.follower_id == user_id)
        return int(session.scalar(stmt) or 0)

    def list_followers(self, session: Session, user_id: int) -> list[AuthUser]:
        stmt = (
            select(AuthUser)
            .join(UserFollow, UserFollow.follower_id == AuthUser.id)
            .where(UserFollow.following_id == user_id)
            .order_by(UserFollow.created_at.desc(), UserFollow.id.desc())
        )
        return list(session.scalars(stmt))

    def list_following(self, session: Session, user_id: int) -> list[AuthUser]:
        stmt = (
            select(AuthUser)
            .join(UserFollow, UserFollow.following_id == AuthUser.id)
            .where(UserFollow.follower_id == user_id)
            .order_by(UserFollow.created_at.desc(), UserFollow.id.desc())
        )
        return list(session.scalars(stmt))
