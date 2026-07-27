"""add OAP 2.1 authentication database foundation

Revision ID: 20260727_oap21_auth_db
Revises: 20260714_report_citations
Create Date: 2026-07-27
"""

from alembic import op


revision = "20260727_oap21_auth_db"
down_revision = "20260714_report_citations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE users (
            id SERIAL PRIMARY KEY,
            email VARCHAR NOT NULL,
            password_hash VARCHAR NOT NULL,
            name VARCHAR,
            status VARCHAR DEFAULT 'ACTIVE' NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            CONSTRAINT uq_users_email UNIQUE (email)
        )
        """
    )
    op.execute("ALTER TABLE analysis_requests ADD COLUMN user_id INTEGER")
    op.execute(
        """
        INSERT INTO users (email, password_hash, name, status)
        VALUES (
            'legacy-system@oap.internal',
            '!LEGACY_SYSTEM_USER_NO_LOGIN!',
            'LEGACY',
            'ACTIVE'
        )
        """
    )
    op.execute(
        """
        UPDATE analysis_requests
        SET user_id = (
            SELECT id
            FROM users
            WHERE email = 'legacy-system@oap.internal'
        )
        WHERE user_id IS NULL
        """
    )
    op.execute("ALTER TABLE analysis_requests ALTER COLUMN user_id SET NOT NULL")
    op.execute(
        """
        ALTER TABLE analysis_requests
        ADD CONSTRAINT fk_analysis_requests_user_id_users
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT
        """
    )
    op.execute(
        """
        CREATE INDEX ix_analysis_requests_user_id_created_at
        ON analysis_requests (user_id, created_at)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_analysis_requests_user_id_created_at")
    op.execute(
        """
        ALTER TABLE analysis_requests
        DROP CONSTRAINT IF EXISTS fk_analysis_requests_user_id_users
        """
    )
    op.execute("ALTER TABLE analysis_requests DROP COLUMN IF EXISTS user_id")
    op.execute("DROP TABLE IF EXISTS users")
