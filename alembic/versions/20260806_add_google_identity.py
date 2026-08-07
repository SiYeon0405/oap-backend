"""add Google identity to users

Revision ID: 20260806_google_identity
Revises: 20260806_split_marketing
Create Date: 2026-08-06
"""

from alembic import op


revision = "20260806_google_identity"
down_revision = "20260806_split_marketing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN google_sub VARCHAR")
    op.execute(
        """
        ALTER TABLE users
        ADD CONSTRAINT uq_users_google_sub UNIQUE (google_sub)
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE users DROP CONSTRAINT IF EXISTS uq_users_google_sub"
    )
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS google_sub")
