"""add retrieval audit tables

Revision ID: 20260710_add_retrieval_audit_tables
Revises: 20260708_kp_pgvector
Create Date: 2026-07-10
"""

from alembic import op


revision = "20260710_retrieval_audit"
down_revision = "20260708_kp_pgvector"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE retrieval_runs (
            id SERIAL PRIMARY KEY,
            analysis_request_id INTEGER NOT NULL
                REFERENCES analysis_requests(id) ON DELETE CASCADE,
            analysis_report_id INTEGER NULL
                REFERENCES analysis_reports(id) ON DELETE SET NULL,
            query TEXT NOT NULL,
            retrieval_method VARCHAR(30) NOT NULL,
            top_k INTEGER NOT NULL,
            embedding_model VARCHAR(100) NULL,
            config_snapshot JSONB NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE retrieval_evidences (
            id SERIAL PRIMARY KEY,
            retrieval_run_id INTEGER NOT NULL
                REFERENCES retrieval_runs(id) ON DELETE CASCADE,
            document_id_snapshot BIGINT NOT NULL,
            chunk_index_snapshot INTEGER NOT NULL,
            content_snapshot TEXT NOT NULL,
            metadata_snapshot JSONB NOT NULL,
            score_snapshot JSONB NOT NULL,
            rank INTEGER NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            CONSTRAINT uq_retrieval_evidences_run_rank
                UNIQUE (retrieval_run_id, rank)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_retrieval_runs_analysis_request_created_at
        ON retrieval_runs (analysis_request_id, created_at)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_retrieval_runs_analysis_request_created_at")
    op.execute("DROP TABLE IF EXISTS retrieval_evidences")
    op.execute("DROP TABLE IF EXISTS retrieval_runs")
