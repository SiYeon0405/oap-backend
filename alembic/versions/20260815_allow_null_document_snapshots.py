"""allow null document snapshots for non-knowledge evidence

Revision ID: 20260815_nullable_evidence_docs
Revises: 20260814_keyword_status
"""

from alembic import op
import sqlalchemy as sa


revision = "20260815_nullable_evidence_docs"
down_revision = "20260814_keyword_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "retrieval_evidences",
        "document_id_snapshot",
        existing_type=sa.BigInteger(),
        nullable=True,
    )
    op.alter_column(
        "retrieval_evidences",
        "chunk_index_snapshot",
        existing_type=sa.Integer(),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "retrieval_evidences",
        "chunk_index_snapshot",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.alter_column(
        "retrieval_evidences",
        "document_id_snapshot",
        existing_type=sa.BigInteger(),
        nullable=False,
    )
