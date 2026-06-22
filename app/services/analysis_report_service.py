from fastapi import HTTPException, status

from app.database.session import get_session
from app.models.analysis_report import AnalysisReport
from app.repositories.analysis_report_repository import AnalysisReportRepository
from app.schemas.analysis_report import AnalysisReportResponse, AnalysisStartResponse


class AnalysisReportService:
    def __init__(self, repository: AnalysisReportRepository | None = None):
        self.repository = repository or AnalysisReportRepository()

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
                updated_request = self.repository.complete_analysis(
                    session,
                    analysis_request,
                )
                return AnalysisStartResponse(
                    requestId=updated_request.id,
                    status=updated_request.status,
                )

            if analysis_request.status != "INTERVIEWING":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="analysis request is not interviewing",
                )

            messages = self.repository.find_messages(session, request_id)
            report_payload = self._build_report_payload(analysis_request, messages)
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

    def _build_report_payload(self, analysis_request, messages) -> dict[str, dict]:
        user_answers = [
            message.content.strip()
            for message in messages
            if message.role == "USER" and message.content.strip()
        ]
        interview_summary = " ".join(user_answers) or "No user answers provided."

        return {
            "service_summary": {
                "serviceName": analysis_request.service_name,
                "description": analysis_request.one_line_description,
                "industry": analysis_request.industry,
                "interviewSummary": interview_summary,
            },
            "market_analysis": {
                "industry": analysis_request.industry,
                "basis": user_answers[:2],
            },
            "competitor_analysis": {
                "strategy": "Compare direct alternatives mentioned in the interview.",
                "basis": user_answers,
            },
            "target_customer_analysis": {
                "strategy": "Prioritize the customer segment and pain points from the interview.",
                "basis": user_answers[:3],
            },
            "marketing_strategy": {
                "strategy": "Validate demand through the channels mentioned in the interview.",
                "basis": user_answers,
            },
            "platform_recommendation": {
                "strategy": "Start with the smallest platform that supports the described core feature.",
                "mainQuestion": analysis_request.main_question,
            },
        }
