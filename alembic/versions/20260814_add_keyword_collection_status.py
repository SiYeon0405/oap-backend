"""add keyword collection status

Revision ID: 20260814_keyword_status
Revises: 20260812_metric_ownership
"""

from alembic import op
import sqlalchemy as sa


revision = "20260814_keyword_status"
down_revision = "20260812_metric_ownership"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "analysis_requests",
        sa.Column(
            "keyword_collection_status",
            sa.String(),
            nullable=True,
            server_default=sa.text("'PENDING'"),
        ),
    )
    op.execute("""
        UPDATE analysis_requests AS ar
        SET keyword_collection_status = CASE
            WHEN EXISTS (
                SELECT 1
                FROM keyword_metrics AS km
                WHERE km.analysis_request_id = ar.id
            ) THEN 'COMPLETED'
            ELSE 'PENDING'
        END
    """)
    op.alter_column(
        "analysis_requests",
        "keyword_collection_status",
        existing_type=sa.String(),
        nullable=False,
    )
    op.create_check_constraint(
        "ck_analysis_requests_keyword_collection_status",
        "analysis_requests",
        "keyword_collection_status IN ('PENDING','COLLECTING','COMPLETED','FAILED')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_analysis_requests_keyword_collection_status",
        "analysis_requests",
        type_="check",
    )
    op.drop_column("analysis_requests", "keyword_collection_status")
