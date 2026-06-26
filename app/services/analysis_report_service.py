from fastapi import HTTPException, status

from app.ai.report_ai import generate_analysis_report
from app.database.session import get_session
from app.models.analysis_report import AnalysisReport
from app.repositories.analysis_report_repository import AnalysisReportRepository
from app.repositories.interview_message_repository import InterviewMessageRepository
from app.schemas.analysis_report import AnalysisReportResponse, AnalysisStartResponse


class AnalysisReportService:
    def __init__(
        self,
        repository: AnalysisReportRepository | None = None,
        interview_message_repository: InterviewMessageRepository | None = None,
    ):
        self.repository = repository or AnalysisReportRepository()
        self.interview_message_repository = (
            interview_message_repository or InterviewMessageRepository()
        )

    def start_analysis(self, request_id: int) -> AnalysisStartResponse:
        with get_session() as session:
            analysis_request = self.repository.find_analysis_request(session, request_id)
            if analysis_request is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="analysis request not found",
                )

            existing_report = self.repository.find_report(session, request_id)
            if existing_report is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="analysis report already exists",
                )

            try:
                interview_messages = self.interview_message_repository.find_messages(
                    session,
                    request_id,
                )
            except Exception:
                interview_messages = None

            report_payload = generate_analysis_report(
                analysis_request,
                interview_messages,
            )
            analysis_report = AnalysisReport(
                analysis_request_id=request_id,
                **report_payload,
            )
            updated_request = self.repository.start_analysis(
                session,
                analysis_request,
                analysis_report,
            )

            return AnalysisStartResponse(
                requestId=updated_request.id,
                status=updated_request.status,
            )

    def get_report(self, request_id: int) -> AnalysisReportResponse:
        with get_session() as session:
            analysis_request = self.repository.find_analysis_request(session, request_id)
            if analysis_request is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="analysis request not found",
                )

            report = self.repository.find_report(session, request_id)
            if report is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="analysis report not found",
                )

            return AnalysisReportResponse(
                serviceSummary=report.service_summary,
                marketAnalysis=report.market_analysis,
                competitorAnalysis=report.competitor_analysis,
                targetCustomerAnalysis=report.target_customer_analysis,
                marketingStrategy=report.marketing_strategy,
                platformRecommendation=report.platform_recommendation,
            )

