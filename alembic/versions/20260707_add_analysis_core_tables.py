"""add analysis core tables

Revision ID: 20260707_analysis_core
Revises:
Create Date: 2026-07-07
"""

from alembic import op


revision = "20260707_analysis_core"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE analysis_requests (
            id SERIAL PRIMARY KEY,
            service_name VARCHAR(100) NOT NULL,
            one_line_description VARCHAR(255) NOT NULL,
            industry VARCHAR(100) NOT NULL,
            main_question TEXT NOT NULL,
            status VARCHAR(30) DEFAULT 'INTERVIEWING' NOT NULL,
            interview_completed BOOLEAN DEFAULT false NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_analysis_requests_id
        ON analysis_requests (id)
        """
    )
    op.execute(
        """
        CREATE TABLE analysis_reports (
            id SERIAL PRIMARY KEY,
            analysis_request_id INTEGER NOT NULL
                REFERENCES analysis_requests(id),
            service_summary JSONB NOT NULL,
            market_analysis JSONB NOT NULL,
            competitor_analysis JSONB NOT NULL,
            target_customer_analysis JSONB NOT NULL,
            marketing_strategy JSONB NOT NULL,
            platform_recommendation JSONB NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX ix_analysis_reports_analysis_request_id
        ON analysis_reports (analysis_request_id)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_analysis_reports_id
        ON analysis_reports (id)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_analysis_reports_id")
    op.execute("DROP INDEX IF EXISTS ix_analysis_reports_analysis_request_id")
    op.execute("DROP TABLE IF EXISTS analysis_reports")
    op.execute("DROP INDEX IF EXISTS ix_analysis_requests_id")
    op.execute("DROP TABLE IF EXISTS analysis_requests")
