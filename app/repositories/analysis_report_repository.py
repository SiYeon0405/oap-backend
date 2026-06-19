from sqlalchemy.orm import Session

from app.models.analysis_report import AnalysisReport
from app.models.analysis_request import AnalysisRequest


class AnalysisReportRepository:
    def find_analysis_request(
        self,
        session: Session,
        request_id: int,
    ) -> AnalysisRequest | None:
        return session.get(AnalysisRequest, request_id)

    def find_report(
        self,
        session: Session,
        request_id: int,
    ) -> AnalysisReport | None:
        return (
            session.query(AnalysisReport)
            .filter(AnalysisReport.analysis_request_id == request_id)
            .first()
        )

    def start_analysis(
        self,
        session: Session,
        analysis_request: AnalysisRequest,
        analysis_report: AnalysisReport,
    ) -> AnalysisRequest:
        analysis_request.status = "PROCESSING"
        session.add(analysis_report)
        session.commit()
        session.refresh(analysis_request)
        return analysis_request
