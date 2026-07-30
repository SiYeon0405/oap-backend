"""cascade user-owned analysis data

Revision ID: 20260730_user_data_cascade
Revises: 20260730_refresh_sessions
Create Date: 2026-07-30
"""

from alembic import op


revision = "20260730_user_data_cascade"
down_revision = "20260730_refresh_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE analysis_requests
        DROP CONSTRAINT fk_analysis_requests_user_id_users,
        ADD CONSTRAINT fk_analysis_requests_user_id_users
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        """
    )
    op.execute(
        """
        ALTER TABLE interview_messages
        DROP CONSTRAINT interview_messages_analysis_request_id_fkey,
        ADD CONSTRAINT interview_messages_analysis_request_id_fkey
            FOREIGN KEY (analysis_request_id)
            REFERENCES analysis_requests(id) ON DELETE CASCADE
        """
    )
    op.execute(
        """
        ALTER TABLE analysis_reports
        DROP CONSTRAINT analysis_reports_analysis_request_id_fkey,
        ADD CONSTRAINT analysis_reports_analysis_request_id_fkey
            FOREIGN KEY (analysis_request_id)
            REFERENCES analysis_requests(id) ON DELETE CASCADE
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE analysis_reports
        DROP CONSTRAINT analysis_reports_analysis_request_id_fkey,
        ADD CONSTRAINT analysis_reports_analysis_request_id_fkey
            FOREIGN KEY (analysis_request_id)
            REFERENCES analysis_requests(id) ON DELETE NO ACTION
        """
    )
    op.execute(
        """
        ALTER TABLE interview_messages
        DROP CONSTRAINT interview_messages_analysis_request_id_fkey,
        ADD CONSTRAINT interview_messages_analysis_request_id_fkey
            FOREIGN KEY (analysis_request_id)
            REFERENCES analysis_requests(id) ON DELETE NO ACTION
        """
    )
    op.execute(
        """
        ALTER TABLE analysis_requests
        DROP CONSTRAINT fk_analysis_requests_user_id_users,
        ADD CONSTRAINT fk_analysis_requests_user_id_users
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT
        """
    )
