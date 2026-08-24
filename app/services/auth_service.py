import os
from hashlib import sha256
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import bcrypt
import jwt
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.database.session import get_session
from app.models.refresh_token_session import RefreshTokenSession
from app.models.user import User
from app.schemas.auth import (
    DeleteAccountRequest,
    GoogleLoginRequest,
    LoginRequest,
    SignupRequest,
)
from app.services.google_identity_service import (
    GoogleIdentityService,
    GoogleIdentityConfigurationError,
    GoogleTokenVerificationError,
)
from app.services.user_consent_service import UserConsentService


class EmailAlreadyExistsError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


class AccountDeletionError(Exception):
    pass


class AccountDeletionConfigurationError(Exception):
    pass


class GoogleEmailConflictError(Exception):
    pass


@dataclass(frozen=True)
class LoginResult:
    user: User
    access_token: str
    refresh_token: str


LEGACY_SYSTEM_EMAIL = "legacy-system@oap.internal"
DEFAULT_JWT_ISSUER = "oap-backend"
DEFAULT_JWT_AUDIENCE = "oap-web"
DEFAULT_ACCESS_EXPIRE_MINUTES = 30
DEFAULT_REFRESH_EXPIRE_DAYS = 14
DUMMY_PASSWORD_HASH = bcrypt.hashpw(
    b"invalid-login-password",
    bcrypt.gensalt(),
)
GOOGLE_ACCOUNT_PASSWORD_HASH = "!GOOGLE_ACCOUNT_NO_PASSWORD!"


class AuthService:
    def signup(
        self,
        request: SignupRequest,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> User:
        with get_session() as session:
            existing_user = session.scalar(
                select(User).where(User.email == request.email)
            )
            if existing_user is not None:
                raise EmailAlreadyExistsError

            user = User(
                email=request.email,
                password_hash=bcrypt.hashpw(
                    request.password.encode("utf-8"),
                    bcrypt.gensalt(),
                ).decode("utf-8"),
                name=request.name,
                status="ACTIVE",
            )
            session.add(user)

            try:
                session.flush()
                UserConsentService().add_initial_consents(
                    session,
                    user.id,
                    terms_agreed=request.termsAgreed,
                    privacy_agreed=request.privacyAgreed,
                    marketing_agreed=request.marketingAgreed,
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise EmailAlreadyExistsError from exc
            except Exception:
                session.rollback()
                raise

            session.refresh(user)
            return user

    def login(self, request: LoginRequest) -> LoginResult:
        with get_session() as session:
            user = session.scalar(select(User).where(User.email == request.email))
            password_hash = (
                user.password_hash.encode("utf-8")
                if user is not None
                else DUMMY_PASSWORD_HASH
            )

            try:
                password_matches = bcrypt.checkpw(
                    request.password.encode("utf-8"),
                    password_hash,
                )
            except ValueError:
                password_matches = False

            if (
                user is None
                or not password_matches
                or user.email == LEGACY_SYSTEM_EMAIL
                or user.status != "ACTIVE"
            ):
                raise InvalidCredentialsError

            return self._issue_login_result(session, user)

    def google_login(
        self,
        request: GoogleLoginRequest,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
        identity_service: GoogleIdentityService | None = None,
    ) -> LoginResult:
        identity = (identity_service or GoogleIdentityService()).verify(
            request.idToken
        )
        with get_session() as session:
            user = session.scalar(
                select(User).where(User.google_sub == identity.sub)
            )
            if user is not None:
                if user.status != "ACTIVE" or user.email == LEGACY_SYSTEM_EMAIL:
                    raise InvalidCredentialsError
                return self._issue_login_result(session, user)

            if session.scalar(select(User).where(User.email == identity.email)):
                raise GoogleEmailConflictError

            user = User(
                email=identity.email,
                password_hash=GOOGLE_ACCOUNT_PASSWORD_HASH,
                name=identity.name,
                google_sub=identity.sub,
                status="ACTIVE",
            )
            session.add(user)
            try:
                session.flush()
                UserConsentService().add_initial_consents(
                    session,
                    user.id,
                    terms_agreed=request.termsAgreed,
                    privacy_agreed=request.privacyAgreed,
                    marketing_agreed=request.marketingAgreed,
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
                return self._issue_login_result(session, user)
            except IntegrityError as exc:
                session.rollback()
                raise GoogleEmailConflictError from exc
            except Exception:
                session.rollback()
                raise

    def _issue_login_result(self, session, user: User) -> LoginResult:
        user.last_login_at = datetime.now(timezone.utc)
        access_expiry = timedelta(minutes=self.get_access_expire_minutes())
        refresh_expiry = timedelta(days=self.get_refresh_expire_days())
        token_family = str(uuid4())
        refresh_jti = str(uuid4())
        access_token = self._create_token(
            user.id,
            token_type="access",
            expires_delta=access_expiry,
            jti=str(uuid4()),
        )
        refresh_token = self._create_token(
            user.id,
            token_type="refresh",
            expires_delta=refresh_expiry,
            jti=refresh_jti,
            token_family=token_family,
        )
        session.add(
            RefreshTokenSession(
                user_id=user.id,
                token_hash=self._hash_refresh_token(refresh_token),
                token_family=token_family,
                jti=refresh_jti,
                expires_at=datetime.now(timezone.utc) + refresh_expiry,
            )
        )
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            raise
        session.refresh(user)
        return LoginResult(
            user=user,
            access_token=access_token,
            refresh_token=refresh_token,
        )

    def get_current_user(self, access_token: str) -> User:
        payload = self._decode_token(access_token, "access")
        user_id = int(payload["sub"])

        with get_session() as session:
            user = session.scalar(
                select(User).where(
                    User.id == user_id,
                    User.status == "ACTIVE",
                    User.email != LEGACY_SYSTEM_EMAIL,
                )
            )
            if user is None:
                raise InvalidCredentialsError
            return user

    def refresh(self, refresh_token: str) -> LoginResult:
        payload = self._decode_token(refresh_token, "refresh")
        token_hash = self._hash_refresh_token(refresh_token)
        now = datetime.now(timezone.utc)

        with get_session() as session:
            stored = session.scalar(
                select(RefreshTokenSession)
                .where(RefreshTokenSession.token_hash == token_hash)
                .with_for_update()
            )
            if stored is None:
                raise InvalidCredentialsError

            if (
                stored.user_id != int(payload["sub"])
                or stored.jti != payload["jti"]
                or stored.token_family != payload["token_family"]
            ):
                self._revoke_family(
                    session,
                    stored.token_family,
                    now,
                    reason="reused",
                )
                session.commit()
                raise InvalidCredentialsError

            if stored.revoked_at is not None:
                self._revoke_family(
                    session,
                    stored.token_family,
                    now,
                    reason="reused",
                )
                session.commit()
                raise InvalidCredentialsError

            user = session.scalar(
                select(User).where(
                    User.id == stored.user_id,
                    User.status == "ACTIVE",
                    User.email != LEGACY_SYSTEM_EMAIL,
                )
            )
            if user is None or self._as_utc(stored.expires_at) <= now:
                raise InvalidCredentialsError

            access_expiry = timedelta(minutes=self.get_access_expire_minutes())
            refresh_expiry = timedelta(days=self.get_refresh_expire_days())
            next_jti = str(uuid4())
            access_token = self._create_token(
                user.id,
                token_type="access",
                expires_delta=access_expiry,
                jti=str(uuid4()),
            )
            next_refresh_token = self._create_token(
                user.id,
                token_type="refresh",
                expires_delta=refresh_expiry,
                jti=next_jti,
                token_family=stored.token_family,
            )
            stored.revoked_at = now
            stored.replaced_by_jti = next_jti
            stored.revoke_reason = "rotated"
            session.add(
                RefreshTokenSession(
                    user_id=user.id,
                    token_hash=self._hash_refresh_token(next_refresh_token),
                    token_family=stored.token_family,
                    jti=next_jti,
                    expires_at=now + refresh_expiry,
                )
            )
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                raise
            session.refresh(user)
            return LoginResult(
                user=user,
                access_token=access_token,
                refresh_token=next_refresh_token,
            )

    def logout(self, refresh_token: str | None) -> None:
        if not refresh_token:
            return
        try:
            payload = self._decode_token(refresh_token, "refresh")
        except InvalidCredentialsError:
            return

        with get_session() as session:
            stored = session.scalar(
                select(RefreshTokenSession)
                .where(
                    RefreshTokenSession.token_hash
                    == self._hash_refresh_token(refresh_token)
                )
                .with_for_update()
            )
            if (
                stored is not None
                and stored.user_id == int(payload["sub"])
                and stored.token_family == payload["token_family"]
            ):
                self._revoke_family(
                    session,
                    stored.token_family,
                    datetime.now(timezone.utc),
                    reason="logout",
                )
                session.commit()

    def delete_account(
        self,
        user_id: int,
        request: DeleteAccountRequest,
        *,
        identity_service: GoogleIdentityService | None = None,
    ) -> None:
        if (request.password is None) == (request.idToken is None):
            raise AccountDeletionError

        with get_session() as session:
            user = session.scalar(
                select(User)
                .where(
                    User.id == user_id,
                    User.status == "ACTIVE",
                    User.email != LEGACY_SYSTEM_EMAIL,
                )
                .with_for_update()
            )
            if user is None:
                raise AccountDeletionError

            if user.google_sub is not None:
                if request.idToken is None:
                    raise AccountDeletionError
                try:
                    identity = (
                        identity_service or GoogleIdentityService()
                    ).verify_recent(request.idToken)
                except GoogleIdentityConfigurationError as exc:
                    raise AccountDeletionConfigurationError from exc
                except GoogleTokenVerificationError as exc:
                    raise AccountDeletionError from exc
                if identity.sub != user.google_sub:
                    raise AccountDeletionError
            elif request.password is None or not self._password_matches(
                request.password,
                user.password_hash,
            ):
                raise AccountDeletionError

            self._revoke_all_user_sessions(
                session,
                user.id,
                datetime.now(timezone.utc),
                reason="account_deleted",
            )
            session.delete(user)
            session.commit()

    def _create_token(
        self,
        user_id: int,
        token_type: str,
        expires_delta: timedelta,
        jti: str | None = None,
        token_family: str | None = None,
    ) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "sub": str(user_id),
            "iat": now,
            "exp": now + expires_delta,
            "iss": self._get_env_or_default(
                "JWT_ISSUER",
                DEFAULT_JWT_ISSUER,
            ),
            "aud": self._get_env_or_default(
                "JWT_AUDIENCE",
                DEFAULT_JWT_AUDIENCE,
            ),
            "token_type": token_type,
            "jti": jti or str(uuid4()),
        }
        if token_type == "refresh":
            if not token_family:
                raise ValueError("token_family is required for refresh tokens")
            payload["token_family"] = token_family
        return jwt.encode(
            payload,
            self._get_required_env("JWT_SECRET"),
            algorithm="HS256",
        )

    def _decode_token(self, token: str, expected_type: str) -> dict:
        required = ["sub", "iat", "exp", "iss", "aud", "token_type", "jti"]
        if expected_type == "refresh":
            required.append("token_family")
        try:
            payload = jwt.decode(
                token,
                self._get_required_env("JWT_SECRET"),
                algorithms=["HS256"],
                issuer=self._get_env_or_default(
                    "JWT_ISSUER",
                    DEFAULT_JWT_ISSUER,
                ),
                audience=self._get_env_or_default(
                    "JWT_AUDIENCE",
                    DEFAULT_JWT_AUDIENCE,
                ),
                options={"require": required},
            )
            subject = payload["sub"]
            if (
                payload["token_type"] != expected_type
                or not isinstance(subject, str)
                or not subject.isdigit()
                or not self._is_nonempty_string(payload["jti"])
                or (
                    expected_type == "refresh"
                    and not self._is_nonempty_string(payload["token_family"])
                )
            ):
                raise InvalidCredentialsError
            return payload
        except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
            raise InvalidCredentialsError from exc

    @staticmethod
    def _hash_refresh_token(refresh_token: str) -> str:
        return sha256(refresh_token.encode("utf-8")).hexdigest()

    @staticmethod
    def _is_nonempty_string(value: object) -> bool:
        return isinstance(value, str) and bool(value.strip())

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _password_matches(password: str, password_hash: str) -> bool:
        try:
            return bcrypt.checkpw(
                password.encode("utf-8"),
                password_hash.encode("utf-8"),
            )
        except ValueError:
            return False

    @staticmethod
    def _revoke_family(session, token_family: str, now: datetime, reason: str) -> None:
        session.execute(
            update(RefreshTokenSession)
            .where(
                RefreshTokenSession.token_family == token_family,
                RefreshTokenSession.revoked_at.is_(None),
            )
            .values(revoked_at=now, revoke_reason=reason)
        )

    @staticmethod
    def _revoke_all_user_sessions(
        session,
        user_id: int,
        now: datetime,
        reason: str,
    ) -> None:
        session.execute(
            update(RefreshTokenSession)
            .where(
                RefreshTokenSession.user_id == user_id,
                RefreshTokenSession.revoked_at.is_(None),
            )
            .values(revoked_at=now, revoke_reason=reason)
        )

    @classmethod
    def get_access_expire_minutes(cls) -> int:
        return cls._get_positive_int_env(
            "JWT_ACCESS_EXPIRE_MINUTES",
            DEFAULT_ACCESS_EXPIRE_MINUTES,
        )

    @classmethod
    def get_refresh_expire_days(cls) -> int:
        return cls._get_positive_int_env(
            "JWT_REFRESH_EXPIRE_DAYS",
            DEFAULT_REFRESH_EXPIRE_DAYS,
        )

    @staticmethod
    def _get_required_env(name: str) -> str:
        value = os.getenv(name)
        if not value:
            raise RuntimeError(f"{name} is not configured")
        return value

    @staticmethod
    def _get_env_or_default(name: str, default: str) -> str:
        value = os.getenv(name)
        return value if value and value.strip() else default

    @staticmethod
    def _get_positive_int_env(name: str, default: int) -> int:
        value = os.getenv(name)
        if not value or not value.strip():
            return default
        try:
            parsed_value = int(value)
        except ValueError as exc:
            raise RuntimeError(f"{name} must be an integer") from exc
        if parsed_value <= 0:
            raise RuntimeError(f"{name} must be positive")
        return parsed_value
