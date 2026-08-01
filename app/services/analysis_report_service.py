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

            if analysis_request.status == "COMPLETED":
                analysis_request.status = "INTERVIEWING"
                session.commit()
                session.refresh(analysis_request)

            try:
                interview_messages = self.interview_message_repository.find_messages(
                    session,
                    request_id,
                )
            except Exception:
                interview_messages = None

            try:
                retrieval_query = build_report_retrieval_query(
                    analysis_request,
                    interview_messages,
                )
                evidences = retrieve_report_evidences(retrieval_query, top_k=4)
                retrieval_run = (
                    self._record_retrieval_audit(
                        session,
                        analysis_request_id=request_id,
                        query=retrieval_query,
                        evidences=evidences,
                        top_k=4,
                    )
                    if evidences
                    else None
                )
                evidences_with_ids = self._attach_retrieval_evidence_ids(
                    evidences,
                    retrieval_run,
                )
                evidence_context = build_report_evidence_context(evidences_with_ids)
                report_payload, section_evidence_ids = (
                    generate_analysis_report_with_citations(
                        analysis_request,
                        interview_messages,
                        evidence_context=evidence_context,
                    )
                )
                headline_metrics = report_payload.pop("headline_metrics", [])
                valid_section_evidence_ids = (
                    self.report_citation_service.validate_section_evidence_ids(
                        session,
                        retrieval_run_id=retrieval_run.id,
                        section_evidence_ids=section_evidence_ids,
                    )
                    if retrieval_run is not None
                    else {key: [] for key in section_evidence_ids}
                )
                self.report_citation_service.sanitize_report_evidence_ids(
                    report_payload,
                    valid_section_evidence_ids,
                )
                report_payload["service_summary"]["_schemaVersion"] = "3.0"
                report_payload["service_summary"]["_headlineMetrics"] = (
                    headline_metrics
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
                    self.retrieval_audit_service.attach_report(
                        session,
                        retrieval_run.id,
                        saved_report.id,
                    )
                    self.report_citation_service.save_report_citations(
                        session,
                        analysis_report_id=saved_report.id,
                        retrieval_run_id=retrieval_run.id,
                        section_evidence_ids=valid_section_evidence_ids,
                    )
                updated_request.status = "COMPLETED"
                session.commit()
                session.refresh(updated_request)
            except Exception:
                session.rollback()
                raise

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

            citations = self.report_citation_service.get_citations_by_analysis_request_id(
                session,
                request_id,
            )
            evidence_count = sum(len(items) for items in citations.values())
            valid_ids_by_section = {
                section_key: [item["evidence_id"] for item in items]
                for section_key, items in citations.items()
            }
            sections = {
                "service_summary": dict(report.service_summary or {}),
                "market_analysis": dict(report.market_analysis or {}),
                "competitor_analysis": dict(report.competitor_analysis or {}),
                "target_customer_analysis": dict(report.target_customer_analysis or {}),
                "marketing_strategy": dict(report.marketing_strategy or {}),
                "platform_recommendation": dict(report.platform_recommendation or {}),
            }
            schema_version = sections["service_summary"].pop(
                "_schemaVersion",
                "2.1-legacy",
            )
            stored_headline_metrics = sections["service_summary"].pop(
                "_headlineMetrics",
                [],
            )
            self.report_citation_service.sanitize_report_evidence_ids(
                sections,
                valid_ids_by_section,
            )
            headline_metrics = (
                self._build_headline_metrics(
                    stored_headline_metrics,
                    evidence_count,
                    valid_ids_by_section,
                )
                if schema_version == "3.0"
                else []
            )
            return AnalysisReportResponse(
                serviceSummary=sections["service_summary"],
                marketAnalysis=sections["market_analysis"],
                competitorAnalysis=sections["competitor_analysis"],
                targetCustomerAnalysis=sections["target_customer_analysis"],
                marketingStrategy=sections["marketing_strategy"],
                platformRecommendation=sections["platform_recommendation"],
                reportMeta={
                    "schemaVersion": schema_version,
                    "requestId": request_id,
                    "generatedAt": report.created_at,
                    "dataAsOf": None,
                    "overallConfidence": None,
                    "evidenceCount": evidence_count,
                    "analysisLocale": "ko-KR",
                },
                headlineMetrics=headline_metrics,
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
        return self.retrieval_audit_service.record_retrieval(
            session,
            analysis_request_id,
            query,
            evidences,
            retrieval_method="vector",
            top_k=top_k,
        )

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

    @staticmethod
    def _build_headline_metrics(
        stored_metrics: list[dict],
        evidence_count: int,
        valid_ids_by_section: dict[str, list[int]],
    ) -> list[dict]:
        required = {
            "market_attractiveness": {
                "label": "시장 매력도",
                "direction": "higher_is_better",
            },
            "competitive_intensity": {
                "label": "경쟁 강도",
                "direction": "lower_is_better",
            },
            "target_clarity": {
                "label": "타깃 명확도",
                "direction": "higher_is_better",
            },
        }
        stored_by_key = {
            metric.get("key"): metric
            for metric in stored_metrics
            if isinstance(metric, dict) and metric.get("key") in required
        }
        all_evidence_ids = list(
            dict.fromkeys(
                evidence_id
                for ids in valid_ids_by_section.values()
                for evidence_id in ids
            )
        )
        allowed_evidence_ids = set(all_evidence_ids)
        result = []
        for key, contract in required.items():
            metric = dict(stored_by_key.get(key) or {})
            original_evidence_ids = metric.get("evidenceIds", [])
            valid_evidence_ids = [
                evidence_id
                for evidence_id in dict.fromkeys(original_evidence_ids)
                if evidence_id in allowed_evidence_ids
            ]
            metric.update(
                {
                    "key": key,
                    "label": metric.get("label") or contract["label"],
                    "value": metric.get("value"),
                    "unit": "score",
                    "direction": contract["direction"],
                    "valueType": metric.get("valueType") or "estimated",
                    "evidenceIds": valid_evidence_ids,
                }
            )
            if original_evidence_ids and not valid_evidence_ids:
                metric["value"] = None
            result.append(metric)

        result.append(
            {
                "key": "evidence_coverage",
                "label": "근거 커버리지",
                "value": evidence_count,
                "unit": "count",
                "scale": None,
                "direction": "higher_is_better",
                "displayLevel": None,
                "displayText": None,
                "valueType": "observed",
                "confidence": 1,
                "sampleSize": None,
                "evidenceIds": all_evidence_ids,
                "calculation": "실제 report_citations 행 수",
                "asOf": None,
            }
        )
        return result

