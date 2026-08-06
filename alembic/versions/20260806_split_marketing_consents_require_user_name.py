"""split marketing consent history and require user names

Revision ID: 20260806_split_marketing
Revises: 20260804_user_consents
Create Date: 2026-08-06
"""

from alembic import op


revision = "20260806_split_marketing"
down_revision = "20260804_user_consents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE marketing_consents (
            id BIGSERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            document_version VARCHAR(50) NOT NULL,
            is_agreed BOOLEAN NOT NULL,
            occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
            ip_address VARCHAR(45),
            user_agent VARCHAR(512),
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            CONSTRAINT fk_marketing_consents_user_id_users
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_marketing_consents_user_occurred_id
        ON marketing_consents (user_id, occurred_at DESC, id DESC)
        """
    )
    op.execute(
        """
        INSERT INTO marketing_consents (
            user_id, document_version, is_agreed, occurred_at,
            ip_address, user_agent, created_at
        )
        SELECT
            user_id, document_version, is_agreed, occurred_at,
            ip_address, user_agent, created_at
        FROM user_consents
        WHERE consent_type = 'MARKETING'
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF (SELECT count(*) FROM user_consents WHERE consent_type = 'MARKETING')
               <> (SELECT count(*) FROM marketing_consents) THEN
                RAISE EXCEPTION 'marketing consent migration count mismatch';
            END IF;
        END $$
        """
    )
    op.execute("DELETE FROM user_consents WHERE consent_type = 'MARKETING'")
    op.execute(
        "ALTER TABLE user_consents DROP CONSTRAINT ck_user_consents_type"
    )
    op.execute(
        """
        ALTER TABLE user_consents
        ADD CONSTRAINT ck_user_consents_type
        CHECK (consent_type IN ('TERMS', 'PRIVACY'))
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM users WHERE name IS NULL OR btrim(name) = ''
            ) THEN
                RAISE EXCEPTION
                    'users.name contains null or blank values; remediation is required';
            END IF;
        END $$
        """
    )
    op.execute("ALTER TABLE users ALTER COLUMN name SET NOT NULL")


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM user_consents WHERE consent_type = 'MARKETING'
            ) THEN
                RAISE EXCEPTION
                    'user_consents already contains marketing history';
            END IF;
        END $$
        """
    )
    op.execute(
        "ALTER TABLE user_consents DROP CONSTRAINT ck_user_consents_type"
    )
    op.execute(
        """
        ALTER TABLE user_consents
        ADD CONSTRAINT ck_user_consents_type
        CHECK (consent_type IN ('TERMS', 'PRIVACY', 'MARKETING'))
        """
    )
    op.execute(
        """
        INSERT INTO user_consents (
            user_id, consent_type, document_version, is_agreed, occurred_at,
            ip_address, user_agent, created_at
        )
        SELECT
            user_id, 'MARKETING', document_version, is_agreed, occurred_at,
            ip_address, user_agent, created_at
        FROM marketing_consents
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF (SELECT count(*) FROM marketing_consents)
               <> (SELECT count(*) FROM user_consents WHERE consent_type = 'MARKETING') THEN
                RAISE EXCEPTION 'marketing consent restore count mismatch';
            END IF;
        END $$
        """
    )
    op.execute("ALTER TABLE users ALTER COLUMN name DROP NOT NULL")
    op.execute("DROP INDEX IF EXISTS ix_marketing_consents_user_occurred_id")
    op.execute("DROP TABLE marketing_consents")
