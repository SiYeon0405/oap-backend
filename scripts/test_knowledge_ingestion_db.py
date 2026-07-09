import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database.session import get_session
from app.repositories.knowledge_repository import KnowledgeRepository
from app.services.knowledge_ingestion_service import KnowledgeIngestionService


KNOWLEDGE_MARKDOWN_PATH = (
    PROJECT_ROOT / "app" / "ai" / "knowledge" / "report_market_kr.md"
)


def main() -> None:
    repository = KnowledgeRepository()
    service = KnowledgeIngestionService(repository=repository)
    payload = service.prepare_markdown_ingestion(
        KNOWLEDGE_MARKDOWN_PATH,
        source_type="markdown",
        domain="report",
    )

    session = get_session()
    try:
        document = repository.find_document_by_source_path(
            session=session,
            source_path=payload["document"]["source_path"],
        )
        deleted_chunk_count = 0
        if document:
            deleted_chunk_count = repository.delete_chunks_by_document_id(
                session=session,
                document_id=document.id,
            )
        else:
            document = repository.create_document(
                session=session,
                title=payload["document"]["title"],
                source_type=payload["document"]["source_type"],
                source_path=payload["document"]["source_path"],
                domain=payload["document"]["domain"],
            )
        document_id = document.id
        created_chunks = repository.create_chunks(
            session=session,
            document_id=document_id,
            chunks=payload["chunks"],
        )
        created_chunk_count = len(created_chunks)
    finally:
        session.close()

    print("knowledge ingestion db test ok")
    print(f"document_id: {document_id}")
    print(f"deleted_chunk_count: {deleted_chunk_count}")
    print(f"created_chunk_count: {created_chunk_count}")


if __name__ == "__main__":
    main()
