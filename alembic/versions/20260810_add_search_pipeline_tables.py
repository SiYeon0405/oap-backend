"""add search pipeline tables

Revision ID: 20260810_search_pipeline
Revises: 20260806_google_identity
"""

from alembic import op


revision = "20260810_search_pipeline"
down_revision = "20260806_google_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE keywords (
            id SERIAL PRIMARY KEY,
            keyword VARCHAR NOT NULL UNIQUE,
            keyword_raw VARCHAR NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
        )
    """)
    op.execute("""
        CREATE TABLE keyword_metrics (
            id SERIAL PRIMARY KEY,
            keyword_id INTEGER NOT NULL REFERENCES keywords(id),
            pc_count_raw VARCHAR NOT NULL,
            mobile_count_raw VARCHAR NOT NULL,
            pc_count INTEGER NOT NULL,
            mobile_count INTEGER NOT NULL,
            total_count INTEGER NOT NULL,
            comp_idx VARCHAR,
            source VARCHAR DEFAULT 'naver_searchad_keywordstool' NOT NULL,
            collected_at TIMESTAMP WITH TIME ZONE NOT NULL
        )
    """)
    op.execute("CREATE INDEX ix_keyword_metrics_keyword_collected ON keyword_metrics (keyword_id, collected_at DESC)")
    op.execute("""
        CREATE TABLE report_evidences (
            id SERIAL PRIMARY KEY,
            report_id INTEGER NOT NULL REFERENCES analysis_reports(id) ON DELETE CASCADE,
            metric_id INTEGER NOT NULL REFERENCES keyword_metrics(id),
            evidence_no INTEGER NOT NULL,
            seed_type VARCHAR NOT NULL CHECK (seed_type IN ('PROBLEM','SOLUTION','ALTERNATIVE','RECOMMENDATION','PRICE','BRAND')),
            section VARCHAR NOT NULL CHECK (section = 'target_customer_analysis')
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE report_evidences")
    op.execute("DROP INDEX ix_keyword_metrics_keyword_collected")
    op.execute("DROP TABLE keyword_metrics")
    op.execute("DROP TABLE keywords")
