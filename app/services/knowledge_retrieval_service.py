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
        metadata_filter: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        if top_k < 1:
            raise ValueError("top_k must be greater than 0.")

        filters = metadata_filter or {}
        where_conditions = ["kc.embedding <=> kc.embedding = 0"]
        params: dict[str, Any] = {"top_k": top_k}

        if filters.get("domain"):
            where_conditions.append("kd.domain = :domain")
            params["domain"] = filters["domain"]
        if filters.get("source_type"):
            where_conditions.append("kd.source_type = :source_type")
            params["source_type"] = filters["source_type"]
        if filters.get("category"):
            where_conditions.append("kc.metadata ->> 'category' = :category")
            params["category"] = filters["category"]

        query_embedding = self.embedding_service.embed_text(query)
        query_vector = "[" + ",".join(map(str, query_embedding)) + "]"
        params["query_vector"] = query_vector
        rows = session.execute(
            text(
                f"""
                SELECT
                    kc.content,
                    kc.document_id,
                    kc.chunk_index,
                    kc.metadata,
                    1 - (kc.embedding <=> CAST(:query_vector AS vector)) AS similarity_score
                FROM knowledge_chunks kc
                JOIN knowledge_documents kd ON kd.id = kc.document_id
                WHERE {" AND ".join(where_conditions)}
                ORDER BY kc.embedding <=> CAST(:query_vector AS vector)
                LIMIT :top_k
                """
            ),
            params,
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
