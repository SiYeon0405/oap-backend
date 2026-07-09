import sys
from pathlib import Path
from typing import Any

from sqlalchemy import text


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database.session import get_session
from app.services.knowledge_retrieval_service import KnowledgeRetrievalService


QUERY = "시장 분석 기준과 고객 문제를 알려줘"
TOP_K = 3


class CachedEmbeddingService:
    def __init__(self, embedding_service: Any):
        self.embedding_service = embedding_service
        self.cache: dict[str, list[float]] = {}

    def embed_text(self, text_: str) -> list[float]:
        if text_ not in self.cache:
            self.cache[text_] = self.embedding_service.embed_text(text_)
        return self.cache[text_]


def result_keys(results: list[dict[str, Any]]) -> list[tuple[int, int]]:
    return [
        (int(result["document_id"]), int(result["chunk_index"]))
        for result in results
    ]


def first_scalar(session: Any, sql: str) -> Any:
    return session.execute(text(sql)).scalar()


def document_ids_for(session: Any, column_name: str, value: str) -> set[int]:
    rows = session.execute(
        text(
            f"""
            SELECT id
            FROM knowledge_documents
            WHERE {column_name} = :value
            """
        ),
        {"value": value},
    )
    return {int(row[0]) for row in rows}


def main() -> None:
    session = get_session()
    try:
        service = KnowledgeRetrievalService()
        service.embedding_service = CachedEmbeddingService(service.embedding_service)

        no_filter_results = service.retrieve(
            session=session,
            query=QUERY,
            top_k=TOP_K,
            metadata_filter=None,
        )
        assert no_filter_results, "metadata_filter=None should return results"
        print(f"metadata_filter=None: {len(no_filter_results)} results")

        category = first_scalar(
            session,
            """
            SELECT metadata ->> 'category'
            FROM knowledge_chunks
            WHERE metadata ->> 'category' IS NOT NULL
            LIMIT 1
            """,
        )
        assert category, "No category metadata found in knowledge_chunks"
        category_results = service.retrieve(
            session=session,
            query=QUERY,
            top_k=TOP_K,
            metadata_filter={"category": str(category)},
        )
        assert category_results, f"category={category} should return results"
        assert all(
            result.get("metadata", {}).get("category") == category
            for result in category_results
        ), f"All category filter results should have category={category}"
        print(f"category={category}: {len(category_results)} results")

        domain = first_scalar(
            session,
            """
            SELECT domain
            FROM knowledge_documents
            WHERE domain IS NOT NULL
            LIMIT 1
            """,
        )
        if domain:
            domain_results = service.retrieve(
                session=session,
                query=QUERY,
                top_k=TOP_K,
                metadata_filter={"domain": str(domain)},
            )
            allowed_document_ids = document_ids_for(session, "domain", str(domain))
            assert all(
                int(result["document_id"]) in allowed_document_ids
                for result in domain_results
            ), f"All domain filter results should have domain={domain}"
            print(f"domain={domain}: {len(domain_results)} results")
        else:
            print("domain filter skipped: no non-null domain in current DB data")

        source_type = first_scalar(
            session,
            """
            SELECT source_type
            FROM knowledge_documents
            WHERE source_type IS NOT NULL
            LIMIT 1
            """,
        )
        if source_type:
            source_type_results = service.retrieve(
                session=session,
                query=QUERY,
                top_k=TOP_K,
                metadata_filter={"source_type": str(source_type)},
            )
            allowed_document_ids = document_ids_for(
                session,
                "source_type",
                str(source_type),
            )
            assert all(
                int(result["document_id"]) in allowed_document_ids
                for result in source_type_results
            ), f"All source_type filter results should have source_type={source_type}"
            print(f"source_type={source_type}: {len(source_type_results)} results")
        else:
            print("source_type filter skipped: no non-null source_type in current DB data")

        missing_category_results = service.retrieve(
            session=session,
            query=QUERY,
            top_k=TOP_K,
            metadata_filter={"category": "__missing_category__"},
        )
        assert missing_category_results == [], "Missing category should return an empty list"
        print("missing category: 0 results")

        unknown_filter_results = service.retrieve(
            session=session,
            query=QUERY,
            top_k=TOP_K,
            metadata_filter={"unknown_key": "ignored"},
        )
        assert result_keys(unknown_filter_results) == result_keys(no_filter_results), (
            "Unknown filter key should behave the same as no filter"
        )
        print("unknown filter key: same document_id/chunk_index as no filter")

        print("knowledge metadata filter test ok")
    finally:
        session.close()


if __name__ == "__main__":
    main()
