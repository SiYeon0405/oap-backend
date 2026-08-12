"""add keyword metric ownership

Revision ID: 20260812_metric_ownership
Revises: 20260810_search_pipeline
"""

from alembic import op


revision = "20260812_metric_ownership"
down_revision = "20260810_search_pipeline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE keyword_metrics
        ADD COLUMN analysis_request_id INTEGER NULL
            REFERENCES analysis_requests(id) ON DELETE CASCADE,
        ADD COLUMN seed_type VARCHAR NULL
            CHECK (seed_type IN ('PROBLEM','SOLUTION','ALTERNATIVE','RECOMMENDATION','PRICE','BRAND'))
    """)
    op.execute("""
        CREATE INDEX ix_keyword_metrics_request_collected
        ON keyword_metrics (analysis_request_id, collected_at DESC)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX ix_keyword_metrics_request_collected")
    op.execute("ALTER TABLE keyword_metrics DROP COLUMN seed_type")
    op.execute("ALTER TABLE keyword_metrics DROP COLUMN analysis_request_id")
