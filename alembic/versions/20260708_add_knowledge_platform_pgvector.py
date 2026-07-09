"""add knowledge platform pgvector tables

Revision ID: 20260708_add_knowledge_platform_pgvector
Revises:
Create Date: 2026-07-08
"""

from alembic import op


revision = "20260708_kp_pgvector"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE knowledge_documents (
            id BIGSERIAL PRIMARY KEY,
            title VARCHAR(255) NOT NULL,
            source_type VARCHAR(50) NOT NULL,
            source_path TEXT NULL,
            domain VARCHAR(100) NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE knowledge_chunks (
            id BIGSERIAL PRIMARY KEY,
            document_id BIGINT NOT NULL
                REFERENCES knowledge_documents(id) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            embedding vector(1536) NOT NULL,
            metadata JSONB NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
            CONSTRAINT uq_knowledge_chunks_document_chunk_index
                UNIQUE (document_id, chunk_index)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_knowledge_documents_domain
        ON knowledge_documents (domain)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_knowledge_chunks_document_id
        ON knowledge_chunks (document_id)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_knowledge_chunks_chunk_index
        ON knowledge_chunks (chunk_index)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_knowledge_chunks_embedding_ivfflat_cosine
        ON knowledge_chunks
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_knowledge_chunks_embedding_ivfflat_cosine")
    op.execute("DROP INDEX IF EXISTS ix_knowledge_chunks_chunk_index")
    op.execute("DROP INDEX IF EXISTS ix_knowledge_chunks_document_id")
    op.execute("DROP INDEX IF EXISTS ix_knowledge_documents_domain")
    op.execute("DROP TABLE IF EXISTS knowledge_chunks")
    op.execute("DROP TABLE IF EXISTS knowledge_documents")
