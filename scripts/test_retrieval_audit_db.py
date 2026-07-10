import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database.session import get_session
from app.models.analysis_report import AnalysisReport  # Registers analysis_reports metadata.
from app.models.analysis_request import AnalysisRequest
from app.models.retrieval_audit import RetrievalEvidence, RetrievalRun
from app.services.retrieval_audit_service import RetrievalAuditService


def main() -> None:
    session = get_session()
    run_id = None
    analysis_request_id = None
    try:
        analysis_request = (
            session.query(AnalysisRequest)
            .order_by(AnalysisRequest.id.asc())
            .first()
        )
        if analysis_request is None:
            raise RuntimeError("analysis_requests row not found")
        analysis_request_id = int(analysis_request.id)

        metadata_one = {"category": "market", "source": "audit-db-test"}
        metadata_two = {"category": "competitor", "source": "audit-db-test"}
        score_one = {"similarity": 0.91, "text": None, "hybrid": None}
        score_two = {"similarity": 0.82, "text": None, "hybrid": None}

        service = RetrievalAuditService()
        retrieval_run = service.record_retrieval(
            session,
            analysis_request_id=analysis_request_id,
            query="retrieval audit db verification",
            evidences=[
                {
                    "document_id": 1001,
                    "chunk_index": 0,
                    "content": "audit evidence content one",
                    "metadata": metadata_one,
                    "scores": score_one,
                    "rank": 1,
                },
                {
                    "document_id": 1002,
                    "chunk_index": 1,
                    "content": "audit evidence content two",
                    "metadata": metadata_two,
                    "scores": score_two,
                    "rank": 2,
                },
            ],
            retrieval_method="vector",
            top_k=2,
            embedding_model=None,
            config_snapshot={"script": "test_retrieval_audit_db"},
        )
        run_id = retrieval_run.id

        stored_run = session.get(RetrievalRun, run_id)
        if stored_run is None:
            raise AssertionError("stored retrieval run not found")
        if stored_run.analysis_request_id != analysis_request_id:
            raise AssertionError("analysis_request_id mismatch")
        if stored_run.analysis_report_id is not None:
            raise AssertionError("analysis_report_id should be None")

        stored_evidences = (
            session.query(RetrievalEvidence)
            .filter(RetrievalEvidence.retrieval_run_id == run_id)
            .order_by(RetrievalEvidence.rank.asc())
            .all()
        )
        if len(stored_evidences) != 2:
            raise AssertionError("evidence count mismatch")
        if [evidence.rank for evidence in stored_evidences] != [1, 2]:
            raise AssertionError("evidence rank mismatch")
        if stored_evidences[0].metadata_snapshot != metadata_one:
            raise AssertionError("metadata_snapshot mismatch for rank 1")
        if stored_evidences[1].metadata_snapshot != metadata_two:
            raise AssertionError("metadata_snapshot mismatch for rank 2")
        if stored_evidences[0].score_snapshot != score_one:
            raise AssertionError("score_snapshot mismatch for rank 1")
        if stored_evidences[1].score_snapshot != score_two:
            raise AssertionError("score_snapshot mismatch for rank 2")

        session.query(RetrievalEvidence).filter(
            RetrievalEvidence.retrieval_run_id == run_id
        ).delete()
        session.query(RetrievalRun).filter(RetrievalRun.id == run_id).delete()
        session.commit()

        deleted_run = session.get(RetrievalRun, run_id)
        deleted_evidence_count = (
            session.query(RetrievalEvidence)
            .filter(RetrievalEvidence.retrieval_run_id == run_id)
            .count()
        )
        if deleted_run is not None:
            raise AssertionError("retrieval run cleanup failed")
        if deleted_evidence_count != 0:
            raise AssertionError("retrieval evidence cleanup failed")

    except Exception:
        if run_id is not None:
            session.rollback()
            session.query(RetrievalEvidence).filter(
                RetrievalEvidence.retrieval_run_id == run_id
            ).delete()
            session.query(RetrievalRun).filter(RetrievalRun.id == run_id).delete()
            session.commit()
        raise
    finally:
        session.close()

    print("retrieval audit db test ok")
    print(f"analysis_request_id: {analysis_request_id}")
    print(f"retrieval_run_id: {run_id}")
    print("created_evidence_count: 2")
    print("cleanup_verified: true")


if __name__ == "__main__":
    main()
