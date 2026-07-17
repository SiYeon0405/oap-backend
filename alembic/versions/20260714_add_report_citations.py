"""add report citations

Revision ID: 20260714_report_citations
Revises: 20260716_interview_messages
Create Date: 2026-07-14
"""

from alembic import op


revision = "20260714_report_citations"
down_revision = "20260716_interview_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE report_citations (
            id SERIAL PRIMARY KEY,
            analysis_report_id INTEGER NOT NULL
                REFERENCES analysis_reports(id) ON DELETE CASCADE,
            retrieval_evidence_id INTEGER NOT NULL
                REFERENCES retrieval_evidences(id) ON DELETE CASCADE,
            section_key VARCHAR(50) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            CONSTRAINT uq_report_citations_report_section_evidence
                UNIQUE (analysis_report_id, section_key, retrieval_evidence_id),
            CONSTRAINT ck_report_citations_section_key
                CHECK (
                    section_key IN (
                        'service_summary',
                        'market_analysis',
                        'competitor_analysis',
                        'target_customer_analysis',
                        'marketing_strategy',
                        'platform_recommendation'
                    )
                )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_report_citations_analysis_report_section
        ON report_citations (analysis_report_id, section_key)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_report_citations_retrieval_evidence_id
        ON report_citations (retrieval_evidence_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_report_citations_retrieval_evidence_id")
    op.execute("DROP INDEX IF EXISTS ix_report_citations_analysis_report_section")
    op.execute("DROP TABLE IF EXISTS report_citations")
