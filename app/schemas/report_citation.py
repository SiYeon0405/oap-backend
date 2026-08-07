from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class CitationDataPeriod(BaseModel):
    model_config = ConfigDict(extra="allow")

    from_: date | None = Field(default=None, alias="from")
    to: date | None = None


class CitationMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    url: str | None = None
    title: str | None = None
    sourceIdentifier: str | None = None
    publisher: str | None = None
    publishedAt: datetime | date | None = None
    collectedAt: datetime | None = None
    dataPeriod: CitationDataPeriod | None = None
    sampleSize: int | None = Field(default=None, ge=0)
    sourceType: str | None = None
    displayCode: str | None = None
    reliability: float | None = Field(default=None, ge=0, le=1)


class ReportCitationEvidenceResponse(BaseModel):
    evidence_id: int
    content: str
    source: str
    metadata: CitationMetadata


class ReportCitationsResponse(BaseModel):
    service_summary: list[ReportCitationEvidenceResponse]
    market_analysis: list[ReportCitationEvidenceResponse]
    competitor_analysis: list[ReportCitationEvidenceResponse]
    target_customer_analysis: list[ReportCitationEvidenceResponse]
    marketing_strategy: list[ReportCitationEvidenceResponse]
    platform_recommendation: list[ReportCitationEvidenceResponse]
