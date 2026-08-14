from datetime import datetime

from pydantic import BaseModel


class AnalysisRequestCreate(BaseModel):
    serviceName: str
    oneLineDescription: str
    industry: str
    mainQuestion: str


class AnalysisRequestCreateResponse(BaseModel):
    requestId: int
    status: str


class NaverKeywordResponse(BaseModel):
    keyword: str
    keywordRaw: str
    seedType: str | None
    pcCountRaw: str
    mobileCountRaw: str
    pcCount: int
    mobileCount: int
    totalCount: int
    competition: str | None
    source: str
    collectedAt: datetime


class AnalysisRequestNaverKeywordsResponse(BaseModel):
    requestId: int
    collectionStatus: str
    keywords: list[NaverKeywordResponse]
