from sqlalchemy.orm import Session

from app.models.retrieval_audit import RetrievalEvidence, RetrievalRun


class RetrievalAuditRepository:
    def create_run_with_evidences(
        self,
        session: Session,
        payload: dict,
    ) -> RetrievalRun:
        retrieval_run = RetrievalRun(
            analysis_request_id=payload["analysis_request_id"],
            analysis_report_id=payload.get("analysis_report_id"),
            query=payload["query"],
            retrieval_method=payload["retrieval_method"],
            top_k=payload["top_k"],
            embedding_model=payload.get("embedding_model"),
            config_snapshot=payload["config_snapshot"],
        )
        session.add(retrieval_run)
        session.flush()

        evidences = [
            RetrievalEvidence(
                retrieval_run_id=retrieval_run.id,
                document_id_snapshot=evidence["document_id_snapshot"],
                chunk_index_snapshot=evidence["chunk_index_snapshot"],
                content_snapshot=evidence["content_snapshot"],
                metadata_snapshot=evidence.get("metadata_snapshot") or {},
                score_snapshot=evidence.get("score_snapshot") or {},
                rank=evidence["rank"],
            )
            for evidence in payload.get("evidences", [])
        ]
        if evidences:
            session.add_all(evidences)
            session.flush()

        return retrieval_run

    def attach_report(
        self,
        session: Session,
        run_id: int,
        analysis_report_id: int,
    ) -> RetrievalRun | None:
        retrieval_run = session.get(RetrievalRun, run_id)
        if retrieval_run is None:
            return None

        retrieval_run.analysis_report_id = analysis_report_id
        session.flush()
        return retrieval_run

    def find_runs_by_analysis_request_id(
        self,
        session: Session,
        analysis_request_id: int,
    ) -> list[RetrievalRun]:
        return (
            session.query(RetrievalRun)
            .filter(RetrievalRun.analysis_request_id == analysis_request_id)
            .order_by(RetrievalRun.created_at.asc())
            .all()
        )
