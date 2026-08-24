from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from app.models.base import Base


class AdminUser(Base):
    __tablename__ = "admin_users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('analyst', 'support', 'super_admin')",
            name="ck_admin_users_role",
        ),
        CheckConstraint(
            "session_version >= 1",
            name="ck_admin_users_session_version",
        ),
        CheckConstraint(
            "failed_login_count >= 0",
            name="ck_admin_users_failed_login_count",
        ),
    )

    id = Column(Integer, primary_key=True)
    email = Column(String(320), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    name = Column(String(100), nullable=False)
    role = Column(String(32), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    mfa_secret_encrypted = Column(Text, nullable=False)
    session_version = Column(Integer, nullable=False, default=1, server_default=text("1"))
    failed_login_count = Column(Integer, nullable=False, default=0, server_default=text("0"))
    locked_until = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    last_login_at = Column(DateTime(timezone=True), nullable=True)


class AdminMfaChallenge(Base):
    __tablename__ = "admin_mfa_challenges"
    __table_args__ = (
        CheckConstraint(
            "failed_attempts >= 0 AND failed_attempts <= 5",
            name="ck_admin_mfa_challenges_failed_attempts",
        ),
        Index(
            "ix_admin_mfa_challenges_admin_created",
            "admin_id",
            text("created_at DESC"),
        ),
        Index("ix_admin_mfa_challenges_expires_at", "expires_at"),
    )

    id = Column(Uuid, primary_key=True, default=uuid4)
    admin_id = Column(
        Integer,
        ForeignKey("admin_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    expires_at = Column(DateTime(timezone=True), nullable=False)
    consumed_at = Column(DateTime(timezone=True), nullable=True)
    failed_attempts = Column(Integer, nullable=False, default=0, server_default=text("0"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class AdminRefreshTokenSession(Base):
    __tablename__ = "admin_refresh_token_sessions"
    __table_args__ = (
        Index("ix_admin_refresh_sessions_admin_id", "admin_id"),
        Index("ix_admin_refresh_sessions_token_family", "token_family"),
        Index("ix_admin_refresh_sessions_expires_at", "expires_at"),
        Index("ix_admin_refresh_sessions_revoked_at", "revoked_at"),
        Index(
            "ix_admin_refresh_sessions_admin_revoked",
            "admin_id",
            "revoked_at",
        ),
    )

    id = Column(Integer, primary_key=True)
    admin_id = Column(
        Integer,
        ForeignKey("admin_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash = Column(String(64), nullable=False, unique=True)
    jti = Column(String(36), nullable=False, unique=True)
    token_family = Column(String(36), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    replaced_by_jti = Column(String(36), nullable=True)
    revoke_reason = Column(String(32), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_logs"
    __table_args__ = (
        CheckConstraint(
            "result IN ('success', 'failure')",
            name="ck_admin_audit_logs_result",
        ),
        Index(
            "ix_admin_audit_logs_admin_occurred",
            "admin_id",
            text("occurred_at DESC"),
        ),
        Index(
            "ix_admin_audit_logs_action_occurred",
            "action",
            text("occurred_at DESC"),
        ),
        Index(
            "ix_admin_audit_logs_target_occurred",
            "target_type",
            "target_id",
            text("occurred_at DESC"),
        ),
        Index("ix_admin_audit_logs_occurred_id", text("occurred_at DESC"), "id"),
    )

    id = Column(Integer, primary_key=True)
    admin_id = Column(
        Integer,
        ForeignKey("admin_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    action = Column(String(64), nullable=False)
    target_type = Column(String(64), nullable=True)
    target_id = Column(String(128), nullable=True)
    occurred_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    request_id = Column(String(128), nullable=False)
    ip_address_masked = Column(String(64), nullable=True)
    result = Column(String(16), nullable=False)
    audit_metadata = Column(
        "metadata",
        JSONB().with_variant(JSON, "sqlite"),
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )
