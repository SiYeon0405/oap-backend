from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.analysis_report import AnalysisReport
from app.models.analysis_request import AnalysisRequest
from app.models.interview_message import InterviewMessage


class AnalysisReportRepository:
    def find_completed_reports(
        self,
        session: Session,
        user_id: int,
        page: int,
        size: int,
    ) -> tuple[list, int]:
        filters = (
            AnalysisRequest.user_id == user_id,
            AnalysisRequest.status == "COMPLETED",
        )
        items = session.execute(
            select(
                AnalysisRequest.id,
                AnalysisRequest.service_name,
                AnalysisRequest.one_line_description,
                AnalysisRequest.industry,
                AnalysisRequest.status,
                AnalysisRequest.created_at,
            )
            .distinct()
            .join(
                AnalysisReport,
                AnalysisReport.analysis_request_id == AnalysisRequest.id,
            )
            .where(*filters)
            .order_by(
                AnalysisRequest.created_at.desc(),
                AnalysisRequest.id.desc(),
            )
            .offset(page * size)
            .limit(size)
        ).all()
        total = session.scalar(
            select(func.count(func.distinct(AnalysisRequest.id)))
            .select_from(AnalysisRequest)
            .join(
                AnalysisReport,
                AnalysisReport.analysis_request_id == AnalysisRequest.id,
            )
            .where(*filters)
        )
        return items, total or 0

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
        session.commit()
        session.refresh(analysis_request)
        return analysis_request

    def start_analysis(
        self,
        session: Session,
        analysis_request: AnalysisRequest,
        analysis_report: AnalysisReport,
    ) -> tuple[AnalysisRequest, AnalysisReport]:
        session.add(analysis_report)
        session.flush()
        return analysis_request, analysis_report
