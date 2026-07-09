from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.embedding_service import EmbeddingService


class KnowledgeRetrievalService:
    ALLOWED_METADATA_FILTER_KEYS = {"category", "domain", "source_type"}

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

        filters = {
            key: value
            for key, value in (metadata_filter or {}).items()
            if key in self.ALLOWED_METADATA_FILTER_KEYS
        }
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

    def retrieve_hybrid(
        self,
        session: Session,
        query: str,
        top_k: int = 3,
        metadata_filter: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        if top_k < 1:
            raise ValueError("top_k must be greater than 0.")

        filters = {
            key: value
            for key, value in (metadata_filter or {}).items()
            if key in self.ALLOWED_METADATA_FILTER_KEYS
        }
        where_conditions = ["kc.embedding <=> kc.embedding = 0"]
        params: dict[str, Any] = {
            "query": query,
            "rrf_k": 60,
            "top_k": top_k,
        }

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
                WITH query_values AS (
                    SELECT
                        CAST(:query_vector AS vector) AS query_vector,
                        websearch_to_tsquery('simple', :query) AS text_query
                ),
                scored AS (
                    SELECT
                        kc.content,
                        kc.document_id,
                        kc.chunk_index,
                        kc.metadata,
                        1 - (kc.embedding <=> q.query_vector) AS similarity_score,
                        ts_rank(
                            to_tsvector('simple', kc.content),
                            q.text_query
                        ) AS text_score,
                        kc.embedding <=> q.query_vector AS vector_distance
                    FROM knowledge_chunks kc
                    JOIN knowledge_documents kd ON kd.id = kc.document_id
                    CROSS JOIN query_values q
                    WHERE {" AND ".join(where_conditions)}
                ),
                ranked AS (
                    SELECT
                        *,
                        row_number() OVER (
                            ORDER BY vector_distance ASC
                        ) AS vector_rank,
                        row_number() OVER (
                            ORDER BY text_score DESC
                        ) AS text_rank
                    FROM scored
                )
                SELECT
                    content,
                    document_id,
                    chunk_index,
                    metadata,
                    similarity_score,
                    text_score,
                    (
                        1.0 / (:rrf_k + vector_rank)
                        + CASE
                            WHEN text_score > 0 THEN 1.0 / (:rrf_k + text_rank)
                            ELSE 0
                        END
                    ) AS hybrid_score
                FROM ranked
                ORDER BY hybrid_score DESC, vector_rank ASC
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
                "text_score": float(row["text_score"]),
                "hybrid_score": float(row["hybrid_score"]),
            }
            for row in rows
        ]
