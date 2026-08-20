import bcrypt
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select, text

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


BOOTSTRAP_ADVISORY_LOCK_ID = int.from_bytes(b"OAPADMIN", "big")


class AdminBootstrapError(Exception):
    pass


class AdminAlreadyExistsError(AdminBootstrapError):
    pass


@dataclass(frozen=True)
class AdminBootstrapResult:
    account_label: str
    issuer: str
    otpauth_uri: str


class AdminBootstrapService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def create_first_admin(
        self,
        *,
        email: str,
        name: str,
        password: str,
    ) -> AdminBootstrapResult:
        security = get_admin_security_config(self.settings)
        validated = SignupRequest(
            email=email,
            password=password,
            name=name,
            termsAgreed=True,
            privacyAgreed=True,
        )
        now = datetime.now(timezone.utc)

        with get_session() as session:
            try:
                if session.bind.dialect.name == "postgresql":
                    session.execute(
                        text("SELECT pg_advisory_xact_lock(:lock_id)"),
                        {"lock_id": BOOTSTRAP_ADVISORY_LOCK_ID},
                    )
                if session.scalar(select(AdminUser.id).limit(1)) is not None:
                    raise AdminAlreadyExistsError

                password_hash = bcrypt.hashpw(
                    validated.password.encode("utf-8"), bcrypt.gensalt()
                ).decode("utf-8")
                secret = generate_totp_secret()
                encrypted_secret = encrypt_mfa_secret(secret, self.settings)
                admin = AdminUser(
                    email=validated.email,
                    password_hash=password_hash,
                    name=validated.name,
                    role="super_admin",
                    is_active=True,
                    mfa_secret_encrypted=encrypted_secret,
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
                        request_id=f"bootstrap_{uuid4().hex}",
                        ip_address_masked=None,
                        result="success",
                        audit_metadata={},
                    )
                )
                session.commit()
            except AdminAlreadyExistsError:
                session.rollback()
                raise
            except Exception as exc:
                session.rollback()
                raise AdminBootstrapError("Administrator bootstrap failed") from exc

        issuer = security.jwt_issuer
        otpauth_uri = build_totp_uri(secret, validated.email, issuer)
        return AdminBootstrapResult(
            account_label=validated.email,
            issuer=issuer,
            otpauth_uri=otpauth_uri,
        )
