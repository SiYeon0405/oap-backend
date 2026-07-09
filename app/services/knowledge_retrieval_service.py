from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.embedding_service import EmbeddingService


class KnowledgeRetrievalService:
    def __init__(self, embedding_service: EmbeddingService | None = None):
        self.embedding_service = embedding_service or EmbeddingService()

    def retrieve(
        self,
        session: Session,
        query: str,
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        if top_k < 1:
            raise ValueError("top_k must be greater than 0.")

        query_embedding = self.embedding_service.embed_text(query)
        query_vector = "[" + ",".join(map(str, query_embedding)) + "]"
        rows = session.execute(
            text(
                """
                SELECT
                    content,
                    document_id,
                    chunk_index,
                    metadata,
                    1 - (embedding <=> CAST(:query_vector AS vector)) AS similarity_score
                FROM knowledge_chunks
                WHERE embedding <=> embedding = 0
                ORDER BY embedding <=> CAST(:query_vector AS vector)
                LIMIT :top_k
                """
            ),
            {
                "query_vector": query_vector,
                "top_k": top_k,
            },
        ).mappings()

        return [
            {
                "content": row["content"],
                "document_id": row["document_id"],
                "chunk_index": row["chunk_index"],
                "metadata": row["metadata"],
                "similarity_score": float(row["similarity_score"]),
            }
            for row in rows
        ]
