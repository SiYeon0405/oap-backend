"""add administrator authentication foundation

Revision ID: 20260820_admin_auth
Revises: 20260820_analytics_events
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260820_admin_auth"
down_revision = "20260820_analytics_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("mfa_secret_encrypted", sa.Text(), nullable=False),
        sa.Column("session_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("role IN ('analyst', 'support', 'super_admin')", name="ck_admin_users_role"),
        sa.CheckConstraint("session_version >= 1", name="ck_admin_users_session_version"),
        sa.CheckConstraint("failed_login_count >= 0", name="ck_admin_users_failed_login_count"),
    )
    op.create_table(
        "admin_mfa_challenges",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("admin_id", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("failed_attempts >= 0 AND failed_attempts <= 5", name="ck_admin_mfa_challenges_failed_attempts"),
        sa.ForeignKeyConstraint(["admin_id"], ["admin_users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_admin_mfa_challenges_admin_created", "admin_mfa_challenges", ["admin_id", sa.text("created_at DESC")])
    op.create_index("ix_admin_mfa_challenges_expires_at", "admin_mfa_challenges", ["expires_at"])
    op.create_table(
        "admin_refresh_token_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("admin_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("jti", sa.String(36), nullable=False, unique=True),
        sa.Column("token_family", sa.String(36), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_jti", sa.String(36), nullable=True),
        sa.Column("revoke_reason", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["admin_id"], ["admin_users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_admin_refresh_sessions_admin_id", "admin_refresh_token_sessions", ["admin_id"])
    op.create_index("ix_admin_refresh_sessions_token_family", "admin_refresh_token_sessions", ["token_family"])
    op.create_index("ix_admin_refresh_sessions_expires_at", "admin_refresh_token_sessions", ["expires_at"])
    op.create_index("ix_admin_refresh_sessions_revoked_at", "admin_refresh_token_sessions", ["revoked_at"])
    op.create_index("ix_admin_refresh_sessions_admin_revoked", "admin_refresh_token_sessions", ["admin_id", "revoked_at"])
    op.create_table(
        "admin_audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("admin_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(64), nullable=True),
        sa.Column("target_id", sa.String(128), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column("ip_address_masked", sa.String(64), nullable=True),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.CheckConstraint("result IN ('success', 'failure')", name="ck_admin_audit_logs_result"),
        sa.ForeignKeyConstraint(["admin_id"], ["admin_users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_admin_audit_logs_admin_occurred", "admin_audit_logs", ["admin_id", sa.text("occurred_at DESC")])
    op.create_index("ix_admin_audit_logs_action_occurred", "admin_audit_logs", ["action", sa.text("occurred_at DESC")])
    op.create_index("ix_admin_audit_logs_target_occurred", "admin_audit_logs", ["target_type", "target_id", sa.text("occurred_at DESC")])


def downgrade() -> None:
    op.drop_table("admin_audit_logs")
    op.drop_table("admin_refresh_token_sessions")
    op.drop_table("admin_mfa_challenges")
    op.drop_table("admin_users")
