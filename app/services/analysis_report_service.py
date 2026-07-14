from fastapi import HTTPException, status

from app.ai.report_ai import (
    build_report_evidence_context,
    build_report_retrieval_query,
    generate_analysis_report_with_citations,
)
from app.ai.report_retriever import retrieve_report_evidences
from app.database.session import get_session
from app.models.analysis_report import AnalysisReport
from app.repositories.analysis_report_repository import AnalysisReportRepository
from app.repositories.interview_message_repository import InterviewMessageRepository
from app.schemas.analysis_report import AnalysisReportResponse, AnalysisStartResponse
from app.schemas.report_citation import ReportCitationsResponse
from app.services.report_citation_service import ReportCitationService
from app.services.retrieval_audit_service import RetrievalAuditService


class AnalysisReportService:
    def __init__(
        self,
        repository: AnalysisReportRepository | None = None,
        interview_message_repository: InterviewMessageRepository | None = None,
        retrieval_audit_service: RetrievalAuditService | None = None,
        report_citation_service: ReportCitationService | None = None,
    ):
        self.repository = repository or AnalysisReportRepository()
        self.interview_message_repository = (
            interview_message_repository or InterviewMessageRepository()
        )
        self.retrieval_audit_service = (
            retrieval_audit_service or RetrievalAuditService()
        )
        self.report_citation_service = (
            report_citation_service or ReportCitationService()
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
                updated_request = self.repository.complete_analysis(
                    session,
                    analysis_request,
                )
                return AnalysisStartResponse(
                    requestId=updated_request.id,
                    status=updated_request.status,
                )

            if analysis_request.status != "INTERVIEWING" and not (
                analysis_request.status == "COMPLETED"
                and analysis_request.interview_completed
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="analysis request is not interviewing",
                )

            try:
                interview_messages = self.interview_message_repository.find_messages(
                    session,
                    request_id,
                )
            except Exception:
                interview_messages = None

            retrieval_query = build_report_retrieval_query(
                analysis_request,
                interview_messages,
            )
            evidences = retrieve_report_evidences(retrieval_query, top_k=4)
            retrieval_run = self._record_retrieval_audit(
                session,
                analysis_request_id=request_id,
                query=retrieval_query,
                evidences=evidences,
                top_k=4,
            )
            evidences_with_ids = self._attach_retrieval_evidence_ids(
                evidences,
                retrieval_run,
            )
            evidence_context = build_report_evidence_context(evidences_with_ids)

            report_payload, section_evidence_ids = generate_analysis_report_with_citations(
                analysis_request,
                interview_messages,
                evidence_context=evidence_context,
            )
            analysis_report = AnalysisReport(
                analysis_request_id=request_id,
                **report_payload,
            )
            updated_request, saved_report = self.repository.start_analysis(
                session,
                analysis_request,
                analysis_report,
            )
            if retrieval_run is not None:
                self._attach_report_to_retrieval_run(
                    session,
                    retrieval_run_id=retrieval_run.id,
                    analysis_report_id=saved_report.id,
                )
                self._save_report_citations(
                    session,
                    analysis_report_id=saved_report.id,
                    retrieval_run_id=retrieval_run.id,
                    section_evidence_ids=section_evidence_ids,
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

    def get_report_citations(self, request_id: int) -> ReportCitationsResponse:
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

            citations = self.report_citation_service.get_citations_by_analysis_request_id(
                session,
                request_id,
            )
            return ReportCitationsResponse(**citations)

    def _record_retrieval_audit(
        self,
        session,
        *,
        analysis_request_id: int,
        query: str,
        evidences: list[dict],
        top_k: int,
    ):
        try:
            return self.retrieval_audit_service.record_retrieval(
                session,
                analysis_request_id,
                query,
                evidences,
                retrieval_method="vector",
                top_k=top_k,
            )
        except Exception:
            session.rollback()
            return None

    def _attach_report_to_retrieval_run(
        self,
        session,
        *,
        retrieval_run_id: int,
        analysis_report_id: int,
    ) -> None:
        try:
            self.retrieval_audit_service.attach_report(
                session,
                retrieval_run_id,
                analysis_report_id,
            )
        except Exception:
            session.rollback()

    def _attach_retrieval_evidence_ids(
        self,
        evidences: list[dict],
        retrieval_run,
    ) -> list[dict]:
        if retrieval_run is None:
            return []

        persisted_by_rank = {
            getattr(evidence, "rank", None): getattr(evidence, "id", None)
            for evidence in getattr(retrieval_run, "evidences", []) or []
        }

        evidences_with_ids = []
        for evidence in evidences:
            rank = evidence.get("rank")
            retrieval_evidence_id = persisted_by_rank.get(rank)
            if retrieval_evidence_id is None:
                continue
            evidences_with_ids.append(
                {
                    **evidence,
                    "retrieval_evidence_id": retrieval_evidence_id,
                }
            )
        return evidences_with_ids

    def _save_report_citations(
        self,
        session,
        *,
        analysis_report_id: int,
        retrieval_run_id: int,
        section_evidence_ids: dict[str, list[int]],
    ) -> None:
        try:
            self.report_citation_service.save_report_citations(
                session,
                analysis_report_id=analysis_report_id,
                retrieval_run_id=retrieval_run_id,
                section_evidence_ids=section_evidence_ids,
            )
        except Exception:
            session.rollback()

