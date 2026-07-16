"""add interview messages

Revision ID: 20260716_interview_messages
Revises: 20260710_retrieval_audit
Create Date: 2026-07-16
"""

from alembic import op


revision = "20260716_interview_messages"
down_revision = "20260710_retrieval_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE interview_messages (
            id SERIAL PRIMARY KEY,
            analysis_request_id INTEGER NOT NULL
                REFERENCES analysis_requests(id)
                ON UPDATE NO ACTION
                ON DELETE NO ACTION,
            role VARCHAR(20) NOT NULL,
            content TEXT NOT NULL,
            message_order INTEGER NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_interview_messages_analysis_request_id
        ON interview_messages (analysis_request_id)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_interview_messages_id
        ON interview_messages (id)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_interview_messages_id")
    op.execute("DROP INDEX IF EXISTS ix_interview_messages_analysis_request_id")
    op.execute("DROP TABLE IF EXISTS interview_messages")
