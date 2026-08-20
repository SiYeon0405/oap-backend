import ipaddress
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any
from uuid import uuid4

import jwt
import pyotp
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import Settings, get_settings


ADMIN_ACCESS_COOKIE_NAME = "admin_access_token"
ADMIN_REFRESH_COOKIE_NAME = "admin_refresh_token"
ADMIN_CSRF_COOKIE_NAME = "admin_csrf_token"
ADMIN_CSRF_HEADER_NAME = "X-Admin-CSRF-Token"
ADMIN_MFA_CHALLENGE_MINUTES = 5
ADMIN_MFA_MAX_ATTEMPTS = 5
ADMIN_LOGIN_MAX_ATTEMPTS = 5
ADMIN_LOCK_MINUTES = 15
AUDIT_METADATA_ALLOWLIST = frozenset({"authMethod", "errorCode", "reason", "role"})
AUDIT_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "token",
        "accesstoken",
        "refreshtoken",
        "cookie",
        "authorization",
        "mfacode",
        "mfasecret",
        "question",
        "answer",
    }
)


class AdminSecurityConfigurationError(RuntimeError):
    pass


class AdminTokenError(ValueError):
    pass


class AdminMfaSecretError(ValueError):
    pass


class InvalidAuditMetadataError(ValueError):
    pass


@dataclass(frozen=True)
class AdminSecurityConfig:
    jwt_secret: str
    jwt_issuer: str
    jwt_audience: str
    access_expire_minutes: int
    refresh_expire_days: int
    mfa_encryption_key: str


def get_admin_security_config(settings: Settings | None = None) -> AdminSecurityConfig:
    current = settings or get_settings()
    required = {
        "ADMIN_JWT_SECRET": current.admin_jwt_secret,
        "ADMIN_JWT_ISSUER": current.admin_jwt_issuer,
        "ADMIN_JWT_AUDIENCE": current.admin_jwt_audience,
        "ADMIN_MFA_ENCRYPTION_KEY": current.admin_mfa_encryption_key,
    }
    missing = [name for name, value in required.items() if not value or not value.strip()]
    if missing:
        raise AdminSecurityConfigurationError("Administrator security is not configured")
    if current.admin_access_token_expire_minutes <= 0 or current.admin_refresh_token_expire_days <= 0:
        raise AdminSecurityConfigurationError("Administrator token lifetime is invalid")
    try:
        Fernet(current.admin_mfa_encryption_key.encode("ascii"))
    except (ValueError, TypeError, UnicodeError) as exc:
        raise AdminSecurityConfigurationError("Administrator security is not configured") from exc
    return AdminSecurityConfig(
        jwt_secret=current.admin_jwt_secret,
        jwt_issuer=current.admin_jwt_issuer,
        jwt_audience=current.admin_jwt_audience,
        access_expire_minutes=current.admin_access_token_expire_minutes,
        refresh_expire_days=current.admin_refresh_token_expire_days,
        mfa_encryption_key=current.admin_mfa_encryption_key,
    )


def encrypt_mfa_secret(secret: str, settings: Settings | None = None) -> str:
    if not secret or not secret.strip():
        raise AdminMfaSecretError("MFA secret is invalid")
    config = get_admin_security_config(settings)
    return Fernet(config.mfa_encryption_key.encode("ascii")).encrypt(secret.encode()).decode("ascii")


def decrypt_mfa_secret(ciphertext: str, settings: Settings | None = None) -> str:
    config = get_admin_security_config(settings)
    try:
        return Fernet(config.mfa_encryption_key.encode("ascii")).decrypt(ciphertext.encode("ascii")).decode()
    except (InvalidToken, ValueError, TypeError, UnicodeError) as exc:
        raise AdminMfaSecretError("MFA secret cannot be decrypted") from exc


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def build_totp_uri(secret: str, email: str, issuer: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=issuer)


def verify_totp_code(secret: str, code: str, valid_window: int = 1) -> bool:
    return pyotp.TOTP(secret).verify(code, valid_window=valid_window)


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def create_admin_access_token(
    admin_id: int,
    session_version: int,
    csrf_token: str,
    settings: Settings | None = None,
) -> str:
    if session_version < 1 or not csrf_token:
        raise AdminTokenError("Invalid administrator token data")
    config = get_admin_security_config(settings)
    return _encode_admin_token(
        admin_id,
        "admin_access",
        timedelta(minutes=config.access_expire_minutes),
        csrf_token,
        config,
        session_version=session_version,
    )


def create_admin_refresh_token(
    admin_id: int,
    token_family: str,
    csrf_token: str,
    settings: Settings | None = None,
) -> str:
    if not token_family or not csrf_token:
        raise AdminTokenError("Invalid administrator token data")
    config = get_admin_security_config(settings)
    return _encode_admin_token(
        admin_id,
        "admin_refresh",
        timedelta(days=config.refresh_expire_days),
        csrf_token,
        config,
        token_family=token_family,
    )


def decode_admin_token(
    token: str,
    expected_type: str,
    settings: Settings | None = None,
) -> dict:
    if expected_type not in {"admin_access", "admin_refresh"}:
        raise AdminTokenError("Invalid administrator token")
    config = get_admin_security_config(settings)
    required = ["sub", "iat", "exp", "iss", "aud", "token_type", "jti", "csrf"]
    if expected_type == "admin_access":
        required.append("session_version")
    else:
        required.append("token_family")
    try:
        payload = jwt.decode(
            token,
            config.jwt_secret,
            algorithms=["HS256"],
            issuer=config.jwt_issuer,
            audience=config.jwt_audience,
            options={"require": required},
        )
        subject = payload["sub"]
        if (
            payload["token_type"] != expected_type
            or not isinstance(subject, str)
            or not subject.startswith("admin:")
            or not subject.removeprefix("admin:").isdigit()
            or not _nonempty(payload["jti"])
            or not _nonempty(payload["csrf"])
            or (
                expected_type == "admin_access"
                and (not isinstance(payload["session_version"], int) or payload["session_version"] < 1)
            )
            or (
                expected_type == "admin_refresh"
                and not _nonempty(payload["token_family"])
            )
        ):
            raise AdminTokenError("Invalid administrator token")
        return payload
    except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
        raise AdminTokenError("Invalid administrator token") from exc


def admin_id_from_payload(payload: dict) -> int:
    try:
        subject = payload["sub"]
        if not isinstance(subject, str) or not subject.startswith("admin:"):
            raise ValueError
        admin_id = int(subject.removeprefix("admin:"))
        if admin_id < 1:
            raise ValueError
        return admin_id
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise AdminTokenError("Invalid administrator token") from exc


def session_version_matches(payload: dict, current_version: int) -> bool:
    return payload.get("session_version") == current_version and current_version >= 1


def increment_session_version(admin: Any) -> int:
    current = getattr(admin, "session_version", None)
    if not isinstance(current, int) or current < 1:
        raise ValueError("Invalid administrator session version")
    admin.session_version = current + 1
    return admin.session_version


def hash_admin_refresh_token(token: str) -> str:
    return sha256(token.encode()).hexdigest()


def admin_login_identifier(email: str, settings: Settings | None = None) -> str:
    config = get_admin_security_config(settings)
    return hmac.new(
        config.jwt_secret.encode(),
        email.strip().lower().encode(),
        sha256,
    ).hexdigest()


def csrf_values_match(*values: str | None) -> bool:
    if not values or any(not value for value in values):
        return False
    first = values[0]
    return all(hmac.compare_digest(first, value) for value in values[1:])


def mask_ip_address(value: str | None) -> str | None:
    if not value:
        return None
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return None
    prefix = 24 if address.version == 4 else 64
    return str(ipaddress.ip_network(f"{address}/{prefix}", strict=False).network_address)


def validate_audit_metadata(metadata: dict[str, Any]) -> dict[str, str]:
    validated = {}
    for key, value in metadata.items():
        normalized = "".join(character for character in key.lower() if character.isalnum())
        if normalized in AUDIT_SENSITIVE_KEYS or key not in AUDIT_METADATA_ALLOWLIST:
            raise InvalidAuditMetadataError("Audit metadata is not allowed")
        if not isinstance(value, str) or not value or len(value) > 64:
            raise InvalidAuditMetadataError("Audit metadata is not allowed")
        validated[key] = value
    return validated


def _encode_admin_token(
    admin_id: int,
    token_type: str,
    expires_delta: timedelta,
    csrf_token: str,
    config: AdminSecurityConfig,
    *,
    session_version: int | None = None,
    token_family: str | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": f"admin:{admin_id}",
        "iat": now,
        "exp": now + expires_delta,
        "iss": config.jwt_issuer,
        "aud": config.jwt_audience,
        "token_type": token_type,
        "jti": str(uuid4()),
        "csrf": csrf_token,
    }
    if session_version is not None:
        payload["session_version"] = session_version
    if token_family is not None:
        payload["token_family"] = token_family
    return jwt.encode(payload, config.jwt_secret, algorithm="HS256")


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())
