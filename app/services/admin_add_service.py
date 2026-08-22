import bcrypt
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.database.session import get_session
from app.models.admin import AdminAuditLog, AdminUser
from app.schemas.auth import SignupRequest
from app.services.admin_security import (
    build_totp_uri,
    encrypt_mfa_secret,
    generate_totp_secret,
    get_admin_security_config,
)


ADMIN_ROLES = frozenset({"analyst", "support", "super_admin"})


class AdminAddError(Exception):
    pass


class AdminEmailExistsError(AdminAddError):
    pass


class InvalidAdminRoleError(AdminAddError):
    pass


@dataclass(frozen=True)
class AdminAddResult:
    account_label: str
    issuer: str
    otpauth_uri: str


class AdminAddService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def create_admin(
        self,
        *,
        email: str,
        name: str,
        password: str,
        role: str,
    ) -> AdminAddResult:
        security = get_admin_security_config(self.settings)
        validated = SignupRequest(
            email=email,
            password=password,
            name=name,
            termsAgreed=True,
            privacyAgreed=True,
        )
        if role not in ADMIN_ROLES:
            raise InvalidAdminRoleError
        now = datetime.now(timezone.utc)

        with get_session() as session:
            try:
                if session.scalar(
                    select(AdminUser.id).where(AdminUser.email == validated.email)
                ) is not None:
                    raise AdminEmailExistsError

                password_hash = bcrypt.hashpw(
                    validated.password.encode("utf-8"), bcrypt.gensalt()
                ).decode("utf-8")
                secret = generate_totp_secret()
                admin = AdminUser(
                    email=validated.email,
                    password_hash=password_hash,
                    name=validated.name,
                    role=role,
                    is_active=True,
                    mfa_secret_encrypted=encrypt_mfa_secret(secret, self.settings),
                    session_version=1,
                    failed_login_count=0,
                    locked_until=None,
                    created_at=now,
                    updated_at=now,
                    last_login_at=None,
                )
                session.add(admin)
                session.flush()
                session.add(
                    AdminAuditLog(
                        admin_id=admin.id,
                        action="admin_created",
                        target_type="admin",
                        target_id=str(admin.id),
                        occurred_at=now,
                        request_id=f"add_admin_{uuid4().hex}",
                        ip_address_masked=None,
                        result="success",
                        audit_metadata={},
                    )
                )
                session.commit()
            except AdminEmailExistsError:
                session.rollback()
                raise
            except Exception as exc:
                session.rollback()
                raise AdminAddError("Administrator creation failed") from exc

        return AdminAddResult(
            account_label=validated.email,
            issuer=security.jwt_issuer,
            otpauth_uri=build_totp_uri(secret, validated.email, security.jwt_issuer),
        )
