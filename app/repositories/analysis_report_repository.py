from sqlalchemy.orm import Session

from app.models.analysis_report import AnalysisReport
from app.models.analysis_request import AnalysisRequest
from app.models.interview_message import InterviewMessage


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

    def find_messages(
        self,
        session: Session,
        request_id: int,
    ) -> list[InterviewMessage]:
        return (
            session.query(InterviewMessage)
            .filter(InterviewMessage.analysis_request_id == request_id)
            .order_by(InterviewMessage.message_order.asc())
            .all()
        )

    def complete_analysis(
        self,
        session: Session,
        analysis_request: AnalysisRequest,
    ) -> AnalysisRequest:
        analysis_request.status = "COMPLETED"
        analysis_request.interview_completed = True
        session.commit()
        session.refresh(analysis_request)
        return analysis_request

    def start_analysis(
        self,
        session: Session,
        analysis_request: AnalysisRequest,
        analysis_report: AnalysisReport,
    ) -> AnalysisRequest:
        analysis_request.status = "COMPLETED"
        analysis_request.interview_completed = True
        session.add(analysis_report)
        session.commit()
        session.refresh(analysis_request)
        return analysis_request
