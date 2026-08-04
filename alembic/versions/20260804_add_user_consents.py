"""add user consent history

Revision ID: 20260804_user_consents
Revises: 20260730_user_data_cascade
Create Date: 2026-08-04
"""

from alembic import op


revision = "20260804_user_consents"
down_revision = "20260730_user_data_cascade"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE user_consents (
            id BIGSERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            consent_type VARCHAR(20) NOT NULL,
            document_version VARCHAR(50) NOT NULL,
            is_agreed BOOLEAN NOT NULL,
            occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
            ip_address VARCHAR(45),
            user_agent VARCHAR(512),
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            CONSTRAINT fk_user_consents_user_id_users
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            CONSTRAINT ck_user_consents_type
                CHECK (consent_type IN ('TERMS', 'PRIVACY', 'MARKETING'))
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_user_consents_user_type_occurred_id
        ON user_consents (user_id, consent_type, occurred_at DESC, id DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_consents")
