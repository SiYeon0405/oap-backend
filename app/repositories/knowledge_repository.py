from typing import Any

from sqlalchemy.orm import Session

from app.models.knowledge import KnowledgeChunk, KnowledgeDocument


class KnowledgeRepository:
    def create_document(
        self,
        session: Session,
        title: str,
        source_type: str,
        source_path: str | None = None,
        domain: str | None = None,
    ) -> KnowledgeDocument:
        document = KnowledgeDocument(
            title=title,
            source_type=source_type,
            source_path=source_path,
            domain=domain,
        )
        session.add(document)
        session.commit()
        session.refresh(document)
        return document

    def find_document(
        self,
        session: Session,
        document_id: int,
    ) -> KnowledgeDocument | None:
        return session.get(KnowledgeDocument, document_id)

    def find_document_by_source_path(
        self,
        session: Session,
        source_path: str,
    ) -> KnowledgeDocument | None:
        return (
            session.query(KnowledgeDocument)
            .filter(KnowledgeDocument.source_path == source_path)
            .one_or_none()
        )

    def create_chunks(
        self,
        session: Session,
        document_id: int,
        chunks: list[dict[str, Any]],
    ) -> list[KnowledgeChunk]:
        chunk_models = [
            KnowledgeChunk(
                document_id=document_id,
                chunk_index=int(chunk["chunk_index"]),
                content=str(chunk["content"]),
                embedding=chunk["embedding"],
                metadata_=chunk.get("metadata"),
            )
            for chunk in chunks
        ]
        session.add_all(chunk_models)
        session.commit()
        for chunk_model in chunk_models:
            session.refresh(chunk_model)
        return chunk_models

    def find_chunks_by_document_id(
        self,
        session: Session,
        document_id: int,
    ) -> list[KnowledgeChunk]:
        return (
            session.query(KnowledgeChunk)
            .filter(KnowledgeChunk.document_id == document_id)
            .order_by(KnowledgeChunk.chunk_index.asc())
            .all()
        )

    def delete_chunks_by_document_id(
        self,
        session: Session,
        document_id: int,
    ) -> int:
        return (
            session.query(KnowledgeChunk)
            .filter(KnowledgeChunk.document_id == document_id)
            .delete(synchronize_session=False)
        )
