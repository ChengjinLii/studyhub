from __future__ import annotations

from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from app.models.auth import AuthUser, EmailVerification, LegacyAuthUser


AuthUserModel = AuthUser | LegacyAuthUser
_USER_MODEL_CACHE: dict[str, type[AuthUser] | type[LegacyAuthUser]] = {}


def _bind_cache_key(session: Session) -> str:
    bind = session.get_bind()
    try:
        return bind.engine.url.render_as_string(hide_password=True)
    except Exception:
        return str(bind)


def resolve_user_model(session: Session) -> type[AuthUser] | type[LegacyAuthUser]:
    cache_key = _bind_cache_key(session)
    cached = _USER_MODEL_CACHE.get(cache_key)
    if cached is not None:
        return cached
    inspector = inspect(session.get_bind())
    if inspector.has_table("auth_users"):
        model: type[AuthUser] | type[LegacyAuthUser] = AuthUser
    elif inspector.has_table("users"):
        model = LegacyAuthUser
    else:
        model = AuthUser
    _USER_MODEL_CACHE[cache_key] = model
    return model


class AuthRepository:
    def count_users(self, session: Session) -> int:
        stmt = select(func.count()).select_from(resolve_user_model(session))
        return int(session.scalar(stmt) or 0)

    def find_user_by_id(self, session: Session, user_id: int) -> AuthUserModel | None:
        return session.get(resolve_user_model(session), user_id)

    def find_user_by_username(self, session: Session, username: str) -> AuthUserModel | None:
        user_model = resolve_user_model(session)
        stmt = select(user_model).where(user_model.username == username)
        return session.scalar(stmt)

    def find_user_by_email(self, session: Session, email: str) -> AuthUserModel | None:
        user_model = resolve_user_model(session)
        stmt = select(user_model).where(user_model.email == email)
        return session.scalar(stmt)

    def find_user_by_identifier(self, session: Session, identifier: str) -> AuthUserModel | None:
        if "@" in identifier:
            return self.find_user_by_email(session, identifier)
        return self.find_user_by_username(session, identifier)

    def username_exists(self, session: Session, username: str) -> bool:
        return self.find_user_by_username(session, username) is not None

    def email_exists(self, session: Session, email: str) -> bool:
        return self.find_user_by_email(session, email) is not None

    def build_user(self, session: Session, **kwargs) -> AuthUserModel:
        return resolve_user_model(session)(**kwargs)

    def save_user(self, session: Session, user: AuthUserModel) -> AuthUserModel:
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
