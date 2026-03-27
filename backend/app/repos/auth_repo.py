from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.auth import AuthUser, EmailVerification


class AuthRepository:
    def count_users(self, session: Session) -> int:
        stmt = select(func.count()).select_from(AuthUser)
        return int(session.scalar(stmt) or 0)

    def find_user_by_id(self, session: Session, user_id: int) -> AuthUser | None:
        return session.get(AuthUser, user_id)

    def find_user_by_username(self, session: Session, username: str) -> AuthUser | None:
        stmt = select(AuthUser).where(AuthUser.username == username)
        return session.scalar(stmt)

    def find_user_by_email(self, session: Session, email: str) -> AuthUser | None:
        stmt = select(AuthUser).where(AuthUser.email == email)
        return session.scalar(stmt)

    def find_user_by_identifier(self, session: Session, identifier: str) -> AuthUser | None:
        if "@" in identifier:
            return self.find_user_by_email(session, identifier)
        return self.find_user_by_username(session, identifier)

    def username_exists(self, session: Session, username: str) -> bool:
        return self.find_user_by_username(session, username) is not None

    def email_exists(self, session: Session, email: str) -> bool:
        return self.find_user_by_email(session, email) is not None

    def save_user(self, session: Session, user: AuthUser) -> AuthUser:
        session.add(user)
        session.flush()
        session.refresh(user)
        return user

    def latest_verification(
        self,
        session: Session,
        *,
        email: str,
        purpose: str,
        user_id: int | None = None,
    ) -> EmailVerification | None:
        stmt = select(EmailVerification).where(
            EmailVerification.email == email,
            EmailVerification.purpose == purpose,
        )
        if user_id is None:
            stmt = stmt.where(EmailVerification.user_id.is_(None))
        else:
            stmt = stmt.where(EmailVerification.user_id == user_id)
        stmt = stmt.order_by(EmailVerification.last_sent_at.desc(), EmailVerification.id.desc()).limit(1)
        return session.scalar(stmt)

    def save_verification(self, session: Session, verification: EmailVerification) -> EmailVerification:
        session.add(verification)
        session.flush()
        session.refresh(verification)
        return verification
