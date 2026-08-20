import bcrypt
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import func, select, update

from app.core.config import Settings, get_settings
from app.database.session import get_session
from app.models.admin import (
    AdminAuditLog,
    AdminMfaChallenge,
    AdminRefreshTokenSession,
    AdminUser,
)
from app.services.admin_security import (
    ADMIN_LOCK_MINUTES,
    ADMIN_LOGIN_MAX_ATTEMPTS,
    ADMIN_MFA_CHALLENGE_MINUTES,
    ADMIN_MFA_MAX_ATTEMPTS,
    AdminTokenError,
    admin_id_from_payload,
    admin_login_identifier,
    create_admin_access_token,
    create_admin_refresh_token,
    csrf_values_match,
    decode_admin_token,
    decrypt_mfa_secret,
    generate_csrf_token,
    hash_admin_refresh_token,
    increment_session_version,
    verify_totp_code,
)


DUMMY_ADMIN_PASSWORD_HASH = bcrypt.hashpw(
    b"invalid-admin-login-password",
    bcrypt.gensalt(),
)


class AdminAuthenticationError(Exception):
    pass


class AdminSessionExpiredError(AdminAuthenticationError):
    pass


@dataclass(frozen=True)
class AdminMfaChallengeResult:
    challenge_id: UUID
    expires_in_seconds: int = 300


@dataclass(frozen=True)
class AdminTokenResult:
    admin: AdminUser
    access_token: str
    refresh_token: str
    csrf_token: str


class AdminAuthService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def login(
        self,
        email: str,
        password: str,
        *,
        request_id: str,
        ip_address: str | None,
    ) -> AdminMfaChallengeResult:
        now = datetime.now(timezone.utc)
        target_id = admin_login_identifier(email, self.settings)
        with get_session() as session:
            admin = session.scalar(
                select(AdminUser).where(AdminUser.email == email).with_for_update()
            )
            recent_failures = session.scalar(
                select(func.count(AdminAuditLog.id)).where(
                    AdminAuditLog.target_id == target_id,
                    AdminAuditLog.ip_address_masked == ip_address,
                    AdminAuditLog.action.in_(("admin_login_failed", "admin_login_locked")),
                    AdminAuditLog.occurred_at >= now - timedelta(minutes=ADMIN_LOCK_MINUTES),
                )
            ) or 0
            password_hash = (
                admin.password_hash.encode()
                if admin is not None
                else DUMMY_ADMIN_PASSWORD_HASH
            )
            password_matches = self._password_matches(password, password_hash)

            if admin is None:
                self._audit(
                    session,
                    None,
                    "admin_login_locked" if recent_failures >= ADMIN_LOGIN_MAX_ATTEMPTS - 1 else "admin_login_failed",
                    target_id,
                    request_id,
                    ip_address,
                    "failure",
                )
                session.commit()
                raise AdminAuthenticationError

            if not admin.is_active or self._is_locked(admin, now):
                self._audit(session, admin.id, "admin_login_locked", target_id, request_id, ip_address, "failure")
                session.commit()
                raise AdminAuthenticationError

            if not password_matches:
                admin.failed_login_count += 1
                action = "admin_login_failed"
                if (
                    admin.failed_login_count >= ADMIN_LOGIN_MAX_ATTEMPTS
                    or recent_failures + 1 >= ADMIN_LOGIN_MAX_ATTEMPTS
                ):
                    admin.locked_until = now + timedelta(minutes=ADMIN_LOCK_MINUTES)
                    action = "admin_login_locked"
                self._audit(session, admin.id, action, target_id, request_id, ip_address, "failure")
                session.commit()
                raise AdminAuthenticationError

            challenge = AdminMfaChallenge(
                id=uuid4(),
                admin_id=admin.id,
                expires_at=now + timedelta(minutes=ADMIN_MFA_CHALLENGE_MINUTES),
            )
            session.add(challenge)
            session.commit()
            return AdminMfaChallengeResult(challenge.id)

    def verify_mfa(
        self,
        challenge_id: UUID,
        code: str,
        *,
        request_id: str,
        ip_address: str | None,
    ) -> AdminTokenResult:
        now = datetime.now(timezone.utc)
        with get_session() as session:
            challenge = session.scalar(
                select(AdminMfaChallenge)
                .where(AdminMfaChallenge.id == challenge_id)
                .with_for_update()
            )
            admin = None
            if challenge is not None:
                admin = session.scalar(
                    select(AdminUser)
                    .where(AdminUser.id == challenge.admin_id)
                    .with_for_update()
                )
            invalid = (
                challenge is None
                or admin is None
                or not admin.is_active
                or challenge.consumed_at is not None
                or self._as_utc(challenge.expires_at) <= now
                or challenge.failed_attempts >= ADMIN_MFA_MAX_ATTEMPTS
                or self._is_locked(admin, now)
            )
            if invalid:
                self._audit(session, admin.id if admin else None, "admin_mfa_failed", None, request_id, ip_address, "failure")
                session.commit()
                raise AdminAuthenticationError

            secret = decrypt_mfa_secret(admin.mfa_secret_encrypted, self.settings)
            if not verify_totp_code(secret, code):
                challenge.failed_attempts += 1
                self._audit(session, admin.id, "admin_mfa_failed", None, request_id, ip_address, "failure")
                session.commit()
                raise AdminAuthenticationError

            csrf_token = generate_csrf_token()
            token_family = str(uuid4())
            access_token = create_admin_access_token(
                admin.id, admin.session_version, csrf_token, self.settings
            )
            refresh_token = create_admin_refresh_token(
                admin.id, token_family, csrf_token, self.settings
            )
            refresh_payload = decode_admin_token(
                refresh_token, "admin_refresh", self.settings
            )
            challenge.consumed_at = now
            admin.failed_login_count = 0
            admin.locked_until = None
            admin.last_login_at = now
            session.add(
                AdminRefreshTokenSession(
                    admin_id=admin.id,
                    token_hash=hash_admin_refresh_token(refresh_token),
                    jti=refresh_payload["jti"],
                    token_family=token_family,
                    expires_at=now
                    + timedelta(days=self.settings.admin_refresh_token_expire_days),
                )
            )
            self._audit(session, admin.id, "admin_mfa_succeeded", None, request_id, ip_address, "success")
            self._audit(session, admin.id, "admin_login_succeeded", None, request_id, ip_address, "success")
            session.commit()
            session.refresh(admin)
            return AdminTokenResult(admin, access_token, refresh_token, csrf_token)

    def get_current_admin(self, access_token: str) -> AdminUser:
        try:
            payload = decode_admin_token(access_token, "admin_access", self.settings)
            admin_id = admin_id_from_payload(payload)
        except AdminTokenError as exc:
            raise AdminSessionExpiredError from exc
        with get_session() as session:
            admin = session.scalar(select(AdminUser).where(AdminUser.id == admin_id))
            if (
                admin is None
                or not admin.is_active
                or admin.session_version != payload["session_version"]
            ):
                raise AdminSessionExpiredError
            session.expunge(admin)
            return admin

    def refresh(
        self,
        refresh_token: str,
        csrf_token: str,
        *,
        request_id: str,
        ip_address: str | None,
    ) -> AdminTokenResult:
        now = datetime.now(timezone.utc)
        try:
            payload = decode_admin_token(refresh_token, "admin_refresh", self.settings)
            admin_id = admin_id_from_payload(payload)
            if not csrf_values_match(csrf_token, payload.get("csrf")):
                raise AdminTokenError
        except AdminTokenError as exc:
            self._audit_failure("admin_refresh_failed", request_id, ip_address)
            raise AdminSessionExpiredError from exc

        with get_session() as session:
            admin = session.scalar(
                select(AdminUser).where(AdminUser.id == admin_id).with_for_update()
            )
            stored = session.scalar(
                select(AdminRefreshTokenSession)
                .where(AdminRefreshTokenSession.token_hash == hash_admin_refresh_token(refresh_token))
                .with_for_update()
            )
            if stored is None or admin is None:
                self._audit(session, admin_id if admin else None, "admin_refresh_failed", None, request_id, ip_address, "failure")
                session.commit()
                raise AdminSessionExpiredError
            if stored.revoked_at is not None:
                self._revoke_family(session, admin.id, stored.token_family, now, "reused")
                increment_session_version(admin)
                self._audit(session, admin.id, "admin_refresh_reuse_detected", None, request_id, ip_address, "failure")
                session.commit()
                raise AdminSessionExpiredError
            if (
                not admin.is_active
                or stored.admin_id != admin.id
                or stored.jti != payload["jti"]
                or stored.token_family != payload["token_family"]
                or self._as_utc(stored.expires_at) <= now
            ):
                stored.revoked_at = now
                stored.revoke_reason = "invalid"
                self._audit(session, admin.id, "admin_refresh_failed", None, request_id, ip_address, "failure")
                session.commit()
                raise AdminSessionExpiredError

            next_csrf = generate_csrf_token()
            next_access = create_admin_access_token(
                admin.id, admin.session_version, next_csrf, self.settings
            )
            next_refresh = create_admin_refresh_token(
                admin.id, stored.token_family, next_csrf, self.settings
            )
            next_payload = decode_admin_token(next_refresh, "admin_refresh", self.settings)
            stored.revoked_at = now
            stored.replaced_by_jti = next_payload["jti"]
            stored.revoke_reason = "rotated"
            session.add(
                AdminRefreshTokenSession(
                    admin_id=admin.id,
                    token_hash=hash_admin_refresh_token(next_refresh),
                    jti=next_payload["jti"],
                    token_family=stored.token_family,
                    expires_at=now
                    + timedelta(days=self.settings.admin_refresh_token_expire_days),
                )
            )
            self._audit(session, admin.id, "admin_refresh_succeeded", None, request_id, ip_address, "success")
            session.commit()
            session.refresh(admin)
            return AdminTokenResult(admin, next_access, next_refresh, next_csrf)

    def logout(
        self,
        access_token: str | None,
        refresh_token: str | None,
        *,
        request_id: str,
        ip_address: str | None,
    ) -> None:
        admin_id = self._admin_id_for_logout(access_token, refresh_token)
        now = datetime.now(timezone.utc)
        with get_session() as session:
            admin = None
            if admin_id is not None:
                admin = session.scalar(
                    select(AdminUser).where(AdminUser.id == admin_id).with_for_update()
                )
            if admin is not None:
                session.execute(
                    update(AdminRefreshTokenSession)
                    .where(
                        AdminRefreshTokenSession.admin_id == admin.id,
                        AdminRefreshTokenSession.revoked_at.is_(None),
                    )
                    .values(revoked_at=now, revoke_reason="logout")
                )
                increment_session_version(admin)
            self._audit(session, admin.id if admin else None, "admin_logout_succeeded", None, request_id, ip_address, "success")
            session.commit()

    def _admin_id_for_logout(
        self, access_token: str | None, refresh_token: str | None
    ) -> int | None:
        for token, token_type in (
            (access_token, "admin_access"),
            (refresh_token, "admin_refresh"),
        ):
            if not token:
                continue
            try:
                return admin_id_from_payload(
                    decode_admin_token(token, token_type, self.settings)
                )
            except AdminTokenError:
                continue
        return None

    def _audit_failure(
        self, action: str, request_id: str, ip_address: str | None
    ) -> None:
        with get_session() as session:
            self._audit(session, None, action, None, request_id, ip_address, "failure")
            session.commit()

    @staticmethod
    def _audit(session, admin_id, action, target_id, request_id, ip_address, result):
        session.add(
            AdminAuditLog(
                admin_id=admin_id,
                action=action,
                target_type="admin_account" if target_id else None,
                target_id=target_id,
                request_id=request_id,
                ip_address_masked=ip_address,
                result=result,
                audit_metadata={},
            )
        )

    @staticmethod
    def _password_matches(password: str, password_hash: bytes) -> bool:
        try:
            return bcrypt.checkpw(password.encode(), password_hash)
        except ValueError:
            return False

    @staticmethod
    def _is_locked(admin: AdminUser, now: datetime) -> bool:
        return admin.locked_until is not None and AdminAuthService._as_utc(admin.locked_until) > now

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    @staticmethod
    def _revoke_family(session, admin_id, family, now, reason):
        session.execute(
            update(AdminRefreshTokenSession)
            .where(
                AdminRefreshTokenSession.admin_id == admin_id,
                AdminRefreshTokenSession.token_family == family,
                AdminRefreshTokenSession.revoked_at.is_(None),
            )
            .values(revoked_at=now, revoke_reason=reason)
        )
