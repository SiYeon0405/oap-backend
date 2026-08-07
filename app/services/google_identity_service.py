import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from google.auth.transport.requests import Request
from google.oauth2 import id_token


class GoogleTokenVerificationError(Exception):
    pass


class GoogleIdentityConfigurationError(RuntimeError):
    pass


class GoogleAudienceMismatchError(GoogleTokenVerificationError):
    pass


class GoogleTokenExpiredError(GoogleTokenVerificationError):
    pass


class GoogleEmailNotVerifiedError(GoogleTokenVerificationError):
    pass


class InvalidGoogleProfileError(GoogleTokenVerificationError):
    pass


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    email: str
    name: str


class GoogleIdentityService:
    def verify(self, token: str) -> GoogleIdentity:
        client_id = self._get_client_id()
        self._validate_untrusted_timing_and_audience(token, client_id)
        try:
            claims = id_token.verify_oauth2_token(token, Request(), client_id)
        except ValueError as exc:
            raise GoogleTokenVerificationError from exc

        if claims.get("aud") != client_id:
            raise GoogleAudienceMismatchError
        if claims.get("email_verified") is not True:
            raise GoogleEmailNotVerifiedError

        sub = self._required_string(claims.get("sub"))
        email = self._required_string(claims.get("email")).lower()
        name = self._required_string(claims.get("name"))
        if len(email) > 320 or len(name) > 100:
            raise InvalidGoogleProfileError
        return GoogleIdentity(sub=sub, email=email, name=name)

    def verify_recent(
        self,
        token: str,
        max_age: timedelta = timedelta(minutes=5),
    ) -> GoogleIdentity:
        identity = self.verify(token)
        try:
            claims = jwt.decode(
                token,
                options={
                    "verify_signature": False,
                    "verify_aud": False,
                    "verify_exp": False,
                },
            )
            issued_at = float(claims["iat"])
        except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
            raise GoogleTokenVerificationError from exc

        now = datetime.now(timezone.utc).timestamp()
        if issued_at > now or now - issued_at > max_age.total_seconds():
            raise GoogleTokenVerificationError
        return identity

    @staticmethod
    def _validate_untrusted_timing_and_audience(
        token: str,
        client_id: str,
    ) -> None:
        try:
            claims = jwt.decode(
                token,
                options={
                    "verify_signature": False,
                    "verify_aud": False,
                    "verify_exp": False,
                },
            )
            expires_at = float(claims["exp"])
        except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
            raise GoogleTokenVerificationError from exc
        if claims.get("aud") != client_id:
            raise GoogleAudienceMismatchError
        if expires_at <= datetime.now(timezone.utc).timestamp():
            raise GoogleTokenExpiredError

    @staticmethod
    def _required_string(value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise InvalidGoogleProfileError
        return value.strip()

    @staticmethod
    def _get_client_id() -> str:
        value = os.getenv("GOOGLE_CLIENT_ID")
        if not value or not value.strip():
            raise GoogleIdentityConfigurationError(
                "GOOGLE_CLIENT_ID is not configured"
            )
        return value.strip()
