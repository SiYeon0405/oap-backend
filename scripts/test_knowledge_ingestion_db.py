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
        document = repository.create_document(
            session=session,
            title=payload["document"]["title"],
            source_type=payload["document"]["source_type"],
            source_path=payload["document"]["source_path"],
            domain=payload["document"]["domain"],
        )
        document_id = document.id
        repository.create_chunks(
            session=session,
            document_id=document_id,
            chunks=payload["chunks"],
        )
        chunk_count = len(payload["chunks"])
    finally:
        session.close()

    print("knowledge ingestion db test ok")
    print(f"document_id: {document_id}")
    print(f"chunk_count: {chunk_count}")


if __name__ == "__main__":
    main()
