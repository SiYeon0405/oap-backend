import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database.session import get_session
from app.models.user import User
from app.schemas.auth import LoginRequest, SignupRequest


class EmailAlreadyExistsError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


@dataclass(frozen=True)
class LoginResult:
    user: User
    access_token: str
    refresh_token: str


LEGACY_SYSTEM_EMAIL = "legacy-system@oap.internal"
DUMMY_PASSWORD_HASH = bcrypt.hashpw(
    b"invalid-login-password",
    bcrypt.gensalt(),
)


class AuthService:
    def signup(self, request: SignupRequest) -> User:
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
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise EmailAlreadyExistsError from exc

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

            access_token = self._create_token(
                user.id,
                token_type="access",
                expires_delta=timedelta(
                    minutes=self._get_positive_int_env(
                        "JWT_ACCESS_EXPIRE_MINUTES"
                    )
                ),
            )
            refresh_token = self._create_token(
                user.id,
                token_type="refresh",
                expires_delta=timedelta(
                    days=self._get_positive_int_env("JWT_REFRESH_EXPIRE_DAYS")
                ),
            )
            return LoginResult(
                user=user,
                access_token=access_token,
                refresh_token=refresh_token,
            )

    def get_current_user(self, access_token: str) -> User:
        try:
            payload = jwt.decode(
                access_token,
                self._get_required_env("JWT_SECRET"),
                algorithms=["HS256"],
                issuer=self._get_required_env("JWT_ISSUER"),
                audience=self._get_required_env("JWT_AUDIENCE"),
                options={
                    "require": ["sub", "iat", "exp", "iss", "aud", "token_type"]
                },
            )
            subject = payload["sub"]
            if (
                payload["token_type"] != "access"
                or not isinstance(subject, str)
                or not subject.isdigit()
            ):
                raise InvalidCredentialsError
            user_id = int(subject)
        except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
            raise InvalidCredentialsError from exc

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

    def _create_token(
        self,
        user_id: int,
        token_type: str,
        expires_delta: timedelta,
    ) -> str:
        now = datetime.now(timezone.utc)
        return jwt.encode(
            {
                "sub": str(user_id),
                "iat": now,
                "exp": now + expires_delta,
                "iss": self._get_required_env("JWT_ISSUER"),
                "aud": self._get_required_env("JWT_AUDIENCE"),
                "token_type": token_type,
            },
            self._get_required_env("JWT_SECRET"),
            algorithm="HS256",
        )

    @staticmethod
    def _get_required_env(name: str) -> str:
        value = os.getenv(name)
        if not value:
            raise RuntimeError(f"{name} is not configured")
        return value

    @classmethod
    def _get_positive_int_env(cls, name: str) -> int:
        value = cls._get_required_env(name)
        try:
            parsed_value = int(value)
        except ValueError as exc:
            raise RuntimeError(f"{name} must be an integer") from exc
        if parsed_value <= 0:
            raise RuntimeError(f"{name} must be positive")
        return parsed_value
