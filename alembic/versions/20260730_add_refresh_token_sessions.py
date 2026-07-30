"""add refresh token sessions

Revision ID: 20260730_refresh_sessions
Revises: 20260727_oap21_auth_db
Create Date: 2026-07-30
"""

from alembic import op


revision = "20260730_refresh_sessions"
down_revision = "20260727_oap21_auth_db"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE refresh_token_sessions (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            token_hash VARCHAR NOT NULL,
            token_family VARCHAR NOT NULL,
            jti VARCHAR NOT NULL,
            expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
            revoked_at TIMESTAMP WITH TIME ZONE,
            replaced_by_jti VARCHAR,
            revoke_reason VARCHAR,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            CONSTRAINT fk_refresh_token_sessions_user_id_users
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            CONSTRAINT uq_refresh_token_sessions_token_hash UNIQUE (token_hash),
            CONSTRAINT uq_refresh_token_sessions_jti UNIQUE (jti)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_refresh_token_sessions_user_id
        ON refresh_token_sessions (user_id)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_refresh_token_sessions_token_family
        ON refresh_token_sessions (token_family)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_refresh_token_sessions_expires_at
        ON refresh_token_sessions (expires_at)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_refresh_token_sessions_revoked_at
        ON refresh_token_sessions (revoked_at)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_refresh_token_sessions_user_id_revoked_at
        ON refresh_token_sessions (user_id, revoked_at)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS refresh_token_sessions")
