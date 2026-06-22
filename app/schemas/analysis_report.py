from pydantic import BaseModel


class AnalysisStartResponse(BaseModel):
    requestId: int
    status: str


class AnalysisReportResponse(BaseModel):
    serviceSummary: dict
    marketAnalysis: dict
    competitorAnalysis: dict
    targetCustomerAnalysis: dict
    marketingStrategy: dict
    platformRecommendation: dict
