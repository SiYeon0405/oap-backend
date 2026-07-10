from sqlalchemy.orm import Session

from app.models.retrieval_audit import RetrievalRun
from app.repositories.retrieval_audit_repository import RetrievalAuditRepository


class RetrievalAuditService:
    def __init__(
        self,
        repository: RetrievalAuditRepository | None = None,
    ):
        self.repository = repository or RetrievalAuditRepository()

    def record_retrieval(
        self,
        session: Session,
        analysis_request_id: int,
        query: str,
        evidences: list[dict],
        *,
        retrieval_method: str = "vector",
        top_k: int,
        embedding_model: str | None = None,
        config_snapshot: dict | None = None,
    ) -> RetrievalRun:
        payload = {
            "analysis_request_id": analysis_request_id,
            "analysis_report_id": None,
            "query": query,
            "retrieval_method": retrieval_method,
            "top_k": top_k,
            "embedding_model": embedding_model,
            "config_snapshot": config_snapshot or {},
            "evidences": [
                {
                    "document_id_snapshot": evidence.get("document_id"),
                    "chunk_index_snapshot": evidence.get("chunk_index"),
                    "content_snapshot": evidence.get("content"),
                    "metadata_snapshot": evidence.get("metadata") or {},
                    "score_snapshot": evidence.get("scores") or {},
                    "rank": evidence.get("rank"),
                }
                for evidence in evidences
            ],
        }
        return self.repository.create_run_with_evidences(session, payload)

    def attach_report(
        self,
        session: Session,
        retrieval_run_id: int,
        analysis_report_id: int,
    ) -> RetrievalRun | None:
        return self.repository.attach_report(
            session,
            retrieval_run_id,
            analysis_report_id,
        )
