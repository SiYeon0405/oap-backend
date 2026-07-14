from pydantic import BaseModel


class ReportCitationEvidenceResponse(BaseModel):
    evidence_id: int
    content: str
    source: str
    metadata: dict


class ReportCitationsResponse(BaseModel):
    service_summary: list[ReportCitationEvidenceResponse]
    market_analysis: list[ReportCitationEvidenceResponse]
    competitor_analysis: list[ReportCitationEvidenceResponse]
    target_customer_analysis: list[ReportCitationEvidenceResponse]
    marketing_strategy: list[ReportCitationEvidenceResponse]
    platform_recommendation: list[ReportCitationEvidenceResponse]
