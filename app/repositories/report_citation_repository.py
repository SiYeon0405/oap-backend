from sqlalchemy.orm import Session
from sqlalchemy.orm import joinedload

from app.models.analysis_report import AnalysisReport
from app.models.report_citation import ReportCitation
from app.models.retrieval_audit import RetrievalEvidence


class ReportCitationRepository:
    def replace_report_citations(
        self,
        session: Session,
        analysis_report_id: int,
        section_evidence_ids: dict[str, list[int]],
    ) -> list[ReportCitation]:
        session.query(ReportCitation).filter(
            ReportCitation.analysis_report_id == analysis_report_id
        ).delete()

        citations = [
            ReportCitation(
                analysis_report_id=analysis_report_id,
                section_key=section_key,
                retrieval_evidence_id=evidence_id,
            )
            for section_key, evidence_ids in section_evidence_ids.items()
            for evidence_id in evidence_ids
        ]
        if citations:
            session.add_all(citations)

        session.flush()
        return citations

    def find_by_analysis_request_id(
        self,
        session: Session,
        analysis_request_id: int,
    ) -> list[ReportCitation]:
        return (
            session.query(ReportCitation)
            .options(joinedload(ReportCitation.retrieval_evidence))
            .join(
                AnalysisReport,
                AnalysisReport.id == ReportCitation.analysis_report_id,
            )
            .filter(AnalysisReport.analysis_request_id == analysis_request_id)
            .order_by(ReportCitation.section_key.asc(), ReportCitation.id.asc())
            .all()
        )

    def find_evidences_by_ids(
        self,
        session: Session,
        evidence_ids: list[int],
    ) -> list[RetrievalEvidence]:
        if not evidence_ids:
            return []

        return (
            session.query(RetrievalEvidence)
            .filter(RetrievalEvidence.id.in_(evidence_ids))
            .all()
        )
