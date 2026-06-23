from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import logging
import secrets

import bcrypt
from fastapi import HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import BizException
from app.core.tasks import BackgroundDispatcher
from app.models.auth import AuthUser, EmailVerification
from app.providers.mail import MailMessage, MailProvider
from app.repos.auth_repo import AuthRepository
from app.schemas.auth import (
    BindEmailRequestPayload,
    BindEmailResponsePayload,
    LoginRequestPayload,
    RegisterRequestPayload,
    ResetPasswordRequestPayload,
    VerificationPurpose,
    VerificationSendResponsePayload,
    VerifyEmailRequestPayload,
)
from app.services.auth_cookie_service import AuthCookieService
from app.services.captcha_service import CaptchaService


logger = logging.getLogger(__name__)


class AuthService:
    def __init__(
        self,
        settings: Settings,
        repo: AuthRepository,
        captcha_service: CaptchaService,
        auth_cookie_service: AuthCookieService,
        mail_provider: MailProvider,
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.captcha_service = captcha_service
        self.auth_cookie_service = auth_cookie_service
        self.mail_provider = mail_provider

    def login(self, session: Session, payload: LoginRequestPayload, response: Response) -> dict[str, object]:
        self.captcha_service.validate(payload.captchaId, payload.captchaCode)
        user = self._authenticate_local_user(session, payload.identifier, payload.password)
        remember_me = bool(payload.rememberMe)
        return self.auth_cookie_service.write_auth_cookies_for_user(response, user, remember_me)

    def send_register_code(
        self,
        session: Session,
        payload: RegisterRequestPayload,
        dispatcher: BackgroundDispatcher | None = None,
    ) -> VerificationSendResponsePayload:
        self.captcha_service.validate(payload.captchaId, payload.captchaCode)
        verification = self._create_verification(
            session,
            email=self._normalize_email(payload.email),
            purpose=VerificationPurpose.REGISTER,
            username=self._normalize_username(payload.username),
            password_hash=self._hash_password(payload.password),
        )
        session.commit()
        self._dispatch_verification_email(verification, dispatcher)
        return self._to_send_response(verification)

    def complete_registration(
        self,
        session: Session,
        payload: VerifyEmailRequestPayload,
        response: Response,
    ) -> dict[str, object]:
        if payload.purpose is not VerificationPurpose.REGISTER:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="暂不支持该验证类型")

        verification = self._consume_verification(
            session,
            email=self._normalize_email(payload.email),
            code=payload.code,
            purpose=VerificationPurpose.REGISTER,
            user_id=None,
        )
        if not verification.username or not verification.password_hash:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="注册信息不完整，请重新获取验证码")

        if self.repo.username_exists(session, verification.username):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="USERNAME_EXISTS")
        if self.repo.email_exists(session, verification.email):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="EMAIL_EXISTS")

        user = self.repo.build_user(
            session,
            username=verification.username,
            email=verification.email,
            password_hash=verification.password_hash,
            nickname=verification.username,
            role_mask=self.settings.default_role_mask,
            verified=True,
            free_download_quota=self.settings.initial_download_quota,
            email_privacy=False,
        )
        self.repo.save_user(session, user)
        session.commit()
        session.refresh(user)
        return self.auth_cookie_service.write_auth_cookies_for_user(response, user, remember_me=False)

    def send_reset_password_code(
        self,
        session: Session,
        payload: ResetPasswordRequestPayload,
        dispatcher: BackgroundDispatcher | None = None,
    ) -> VerificationSendResponsePayload:
        if not payload.captchaId or not payload.captchaCode:
            raise BizException("CAPTCHA_REQUIRED", "请先完成验证码验证")
        self.captcha_service.validate(payload.captchaId, payload.captchaCode)

        try:
            user = self._find_identifier_or_404(session, payload.identifier)
        except HTTPException as exc:
            if exc.status_code == status.HTTP_404_NOT_FOUND and self.settings.resolved_password_reset_hide_unknown_account:
                return self._generic_reset_send_response()
            raise
        if not user.email:
            if self.settings.resolved_password_reset_hide_unknown_account:
                return self._generic_reset_send_response()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该账号未绑定邮箱，无法重置密码")

        verification = self._create_verification(
            session,
            email=user.email,
            purpose=VerificationPurpose.RESET,
            user_id=user.id,
        )
        session.commit()
        self._dispatch_verification_email(verification, dispatcher)
        return self._to_send_response(verification)

    def reset_password(self, session: Session, payload: ResetPasswordRequestPayload, response: Response) -> None:
        user = self._find_identifier_or_404(session, payload.identifier)
        if not user.email:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该账号未绑定邮箱，无法重置密码")

        self._consume_verification(
            session,
            email=user.email,
            code=payload.code or "",
            purpose=VerificationPurpose.RESET,
            user_id=user.id,
        )
        user.password_hash = self._hash_password(payload.newPassword)
        self.repo.save_user(session, user)
        session.commit()
        self.auth_cookie_service.clear_auth_cookies(response)

    def bind_email(
        self,
        session: Session,
        user_id: int,
        payload: BindEmailRequestPayload,
        dispatcher: BackgroundDispatcher | None = None,
    ) -> VerificationSendResponsePayload | BindEmailResponsePayload:
        normalized_email = self._normalize_email(payload.email)
        if not payload.code:
            verification = self._create_verification(
                session,
                email=normalized_email,
                purpose=VerificationPurpose.BIND,
                user_id=user_id,
            )
            session.commit()
            self._dispatch_verification_email(verification, dispatcher)
            return self._to_send_response(verification)

        self._consume_verification(
            session,
            email=normalized_email,
            code=payload.code,
            purpose=VerificationPurpose.BIND,
            user_id=user_id,
        )
        if self.repo.email_exists(session, normalized_email):
            existing = self.repo.find_user_by_email(session, normalized_email)
            if existing is None or existing.id != user_id:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="EMAIL_EXISTS")

        user = self.repo.find_user_by_id(session, user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
        user.email = normalized_email
        user.verified = True
        self.repo.save_user(session, user)
        session.commit()
        return BindEmailResponsePayload(email=user.email, verified=bool(user.verified))

    def change_password(
        self,
        session: Session,
        user_id: int,
        old_password: str,
        new_password: str,
        response: Response,
    ) -> None:
        user = self.repo.find_user_by_id(session, user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
        if not user.password_hash or not bcrypt.checkpw(old_password.encode("utf-8"), user.password_hash.encode("utf-8")):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="旧密码不正确")
        user.password_hash = self._hash_password(new_password)
        self.repo.save_user(session, user)
        session.commit()
        self.auth_cookie_service.clear_auth_cookies(response)

    def create_local_user(
        self,
        session: Session,
        *,
        username: str,
        password: str,
        email: str | None = None,
        verified: bool = False,
        nickname: str | None = None,
        user_id: int | None = None,
        role_mask: int | None = None,
    ) -> AuthUser:
        normalized_username = self._normalize_username(username)
        if self.repo.username_exists(session, normalized_username):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="USERNAME_EXISTS")
        normalized_email = self._normalize_email(email) if email else None
        if normalized_email and self.repo.email_exists(session, normalized_email):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="EMAIL_EXISTS")
        user = self.repo.build_user(
            session,
            id=user_id,
            username=normalized_username,
            email=normalized_email,
            password_hash=self._hash_password(password),
            nickname=(nickname or normalized_username).strip() or normalized_username,
            role_mask=self.settings.default_role_mask if role_mask is None else role_mask,
            verified=verified,
            free_download_quota=self.settings.initial_download_quota,
            email_privacy=False,
        )
        self.repo.save_user(session, user)
        session.commit()
        session.refresh(user)
        return user

    def ensure_local_dev_user(self, session: Session) -> AuthUser | None:
        if not self.settings.is_local_dev:
            return None

        normalized_username = self._normalize_username(self.settings.local_dev_username)
        normalized_email = self._normalize_email(self.settings.local_dev_email) if self.settings.local_dev_email else None
        user_by_id = self.repo.find_user_by_id(session, self.settings.local_dev_user_id)
        user_by_username = self.repo.find_user_by_username(session, normalized_username)

        if user_by_id is not None and user_by_username is not None and user_by_id.id != user_by_username.id:
            raise RuntimeError("local-dev developer 账号的固定 ID 与用户名发生冲突，请清理本地数据库后重试。")

        user = user_by_username or user_by_id

        if normalized_email:
            email_owner = self.repo.find_user_by_email(session, normalized_email)
            if email_owner is not None and user is not None and email_owner.id != user.id:
                raise RuntimeError("local-dev developer 账号的邮箱已被其他用户占用，请清理本地数据库后重试。")
            if email_owner is not None and user is None:
                raise RuntimeError("local-dev developer 邮箱已被其他用户占用，请清理本地数据库后重试。")

        if user is None:
            return self.create_local_user(
                session,
                username=normalized_username,
                password=self.settings.local_dev_password,
                email=normalized_email,
                verified=self.settings.local_dev_verified,
                nickname=self.settings.local_dev_nickname,
                user_id=self.settings.local_dev_user_id,
                role_mask=self.settings.local_dev_role_mask,
            )

        user.username = normalized_username
        user.email = normalized_email
        user.password_hash = self._hash_password(self.settings.local_dev_password)
        user.nickname = self.settings.local_dev_nickname.strip() or normalized_username
        user.role_mask = self.settings.local_dev_role_mask
        user.verified = self.settings.local_dev_verified
        user.free_download_quota = self.settings.initial_download_quota
        user.email_privacy = False
        user.status = "active"
        self.repo.save_user(session, user)
        session.commit()
        session.refresh(user)
        return user

    def dev_login(self, session: Session, response: Response) -> dict[str, object]:
        if not self.settings.is_local_dev or not self.settings.local_dev_quick_login_enabled:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="接口不存在")
        user = self.ensure_local_dev_user(session)
        if user is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="local-dev 账号尚未初始化")
        return self.auth_cookie_service.write_auth_cookies_for_user(response, user, remember_me=True)

    def peek_latest_verification_code_for_testing(
        self,
        session: Session,
        *,
        email: str,
        purpose: VerificationPurpose,
        user_id: int | None = None,
    ) -> str | None:
        verification = self.repo.latest_verification(
            session,
            email=self._normalize_email(email),
            purpose=purpose.value,
            user_id=user_id,
        )
        return None if verification is None else verification.code

    def _authenticate_local_user(self, session: Session, identifier: str, raw_password: str) -> AuthUser:
        normalized = self._normalize_login_identifier(identifier)
        user = self._find_user_by_login_identifier(session, normalized)
        if user is None or not user.password_hash:
            self._log_login_failure(normalized, "user_not_found" if user is None else "missing_password_hash")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
        if not bcrypt.checkpw(raw_password.encode("utf-8"), user.password_hash.encode("utf-8")):
            self._log_login_failure(normalized, "password_mismatch", user_id=user.id)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
        if "@" in normalized and user.verified is False:
            self._log_login_failure(normalized, "email_unverified", user_id=user.id)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="邮箱未验证")
        return user

    def _find_identifier_or_404(self, session: Session, identifier: str) -> AuthUser:
        normalized = self._normalize_login_identifier(identifier)
        user = self._find_user_by_login_identifier(session, normalized)
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="账号不存在")
        return user

    def _generic_reset_send_response(self) -> VerificationSendResponsePayload:
        return VerificationSendResponsePayload(
            email="no-reply@study-hub.cn",
            expiresInSeconds=self.settings.verification_ttl_seconds,
            resendAfterSeconds=self.settings.verification_resend_after_seconds,
        )

    def _normalize_login_identifier(self, identifier: str) -> str:
        normalized = identifier.strip()
        if "@" in normalized:
            return normalized.lower()
        return normalized

    def _find_user_by_login_identifier(self, session: Session, identifier: str) -> AuthUser | None:
        user = self.repo.find_user_by_identifier(session, identifier)
        if user is not None or "@" in identifier:
            return user
        lowered = identifier.lower()
        if lowered == identifier:
            return None
        return self.repo.find_user_by_username(session, lowered)

    def _log_login_failure(self, identifier: str, reason: str, *, user_id: int | None = None) -> None:
        identifier_digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:16] if identifier else "-"
        logger.info(
            "Login authentication failed: reason=%s identifier_type=%s identifier_digest=%s user_id=%s",
            reason,
            "email" if "@" in identifier else "username",
            identifier_digest,
            user_id or "-",
            extra={
                "event": "auth_login_failed",
                "failure_reason": reason,
                "user_id": user_id,
                "identifier_digest": identifier_digest,
                "identifier_type": "email" if "@" in identifier else "username",
            },
        )

    def _create_verification(
        self,
        session: Session,
        *,
        email: str,
        purpose: VerificationPurpose,
        user_id: int | None = None,
        username: str | None = None,
        password_hash: str | None = None,
    ) -> EmailVerification:
        latest = self.repo.latest_verification(session, email=email, purpose=purpose.value, user_id=user_id)
        now = self._utcnow()
        resend_cutoff = now - timedelta(seconds=self.settings.verification_resend_after_seconds)
        if latest is not None and latest.last_sent_at > resend_cutoff:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="验证码发送频繁，请稍后再试")

        verification = latest or EmailVerification(
            email=email,
            purpose=purpose.value,
            user_id=user_id,
            code="",
            expires_at=now,
            last_sent_at=now,
            attempts=0,
            max_attempts=self.settings.verification_max_attempts,
            used=False,
        )
        verification.email = email
        verification.purpose = purpose.value
        verification.user_id = user_id
        verification.username = username
        verification.password_hash = password_hash
        verification.code = self._generate_verification_code()
        verification.expires_at = now + timedelta(seconds=self.settings.verification_ttl_seconds)
        verification.last_sent_at = now
        verification.attempts = 0
        verification.max_attempts = self.settings.verification_max_attempts
        verification.used = False
        self.repo.save_verification(session, verification)
        return verification

    def _consume_verification(
        self,
        session: Session,
        *,
        email: str,
        code: str,
        purpose: VerificationPurpose,
        user_id: int | None,
    ) -> EmailVerification:
        verification = self.repo.latest_verification(session, email=email, purpose=purpose.value, user_id=user_id)
        now = self._utcnow()
        if verification is None or verification.used or verification.expires_at < now:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码不存在或已过期")
        if verification.attempts >= verification.max_attempts:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码错误次数过多，请重新获取")
        if verification.user_id is not None and user_id is not None and verification.user_id != user_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码与当前账号不匹配")
        if verification.code != (code or "").strip():
            verification.attempts += 1
            self.repo.save_verification(session, verification)
            session.commit()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码错误")
        verification.used = True
        verification.attempts += 1
        self.repo.save_verification(session, verification)
        return verification

    def _to_send_response(self, verification: EmailVerification) -> VerificationSendResponsePayload:
        expires_at = self._normalize_db_datetime(verification.expires_at)
        expires_in = max(1, int((expires_at - self._utcnow()).total_seconds()))
        return VerificationSendResponsePayload(
            email=verification.email,
            expiresInSeconds=expires_in,
            resendAfterSeconds=self.settings.verification_resend_after_seconds,
        )

    def _generate_verification_code(self) -> str:
        value = secrets.randbelow(10 ** self.settings.verification_code_length)
        return str(value).zfill(self.settings.verification_code_length)

    def _deliver_verification_email(self, verification: EmailVerification) -> None:
        self.mail_provider.send_verification_email(self._build_verification_mail_message(verification))

    async def _deliver_verification_email_async(self, verification: EmailVerification) -> None:
        await self.mail_provider.send_verification_email_async(self._build_verification_mail_message(verification))

    def _dispatch_verification_email(
        self,
        verification: EmailVerification,
        dispatcher: BackgroundDispatcher | None,
    ) -> None:
        if dispatcher is None:
            self._deliver_verification_email(verification)
            return
        dispatcher.schedule(self._deliver_verification_email_async, verification)

    def _build_verification_mail_message(self, verification: EmailVerification) -> MailMessage:
        expires_at = self._normalize_db_datetime(verification.expires_at)
        expires_in = max(1, int((expires_at - self._utcnow()).total_seconds()))
        purpose_label = {
            VerificationPurpose.REGISTER.value: "注册验证",
            VerificationPurpose.BIND.value: "绑定邮箱",
            VerificationPurpose.RESET.value: "重置密码",
        }.get(verification.purpose, "邮箱验证")
        mail_source = "StudyHub local-dev" if self.settings.is_local_dev else "StudyHub"
        subject = f"{mail_source} {purpose_label}"
        return MailMessage(
            purpose=verification.purpose,
            email=verification.email,
            subject=subject,
            code=verification.code,
            username=verification.username,
            expires_in_seconds=expires_in,
            resend_after_seconds=self.settings.verification_resend_after_seconds,
            issued_at=self._utcnow().replace(tzinfo=UTC).isoformat(),
            body_text=(
                f"你好，这是一封来自 {mail_source} 的 {purpose_label} 邮件。\n"
                f"验证码：{verification.code}\n"
                f"有效期：{expires_in} 秒\n"
                f"若非你本人操作，可直接忽略。"
            ),
        )

    def _hash_password(self, raw_password: str) -> str:
        salt = bcrypt.gensalt(rounds=self.settings.bcrypt_rounds)
        return bcrypt.hashpw(raw_password.encode("utf-8"), salt).decode("utf-8")

    def _normalize_username(self, username: str) -> str:
        return username.strip().lower()

    def _normalize_email(self, email: str) -> str:
        return email.strip().lower()

    def _utcnow(self) -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    def _normalize_db_datetime(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value
        return value.astimezone(UTC).replace(tzinfo=None)
