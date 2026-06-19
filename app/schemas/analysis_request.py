from pydantic import BaseModel


class AnalysisRequestCreate(BaseModel):
    serviceName: str
    oneLineDescription: str
    industry: str
    mainQuestion: str


class AnalysisRequestCreateResponse(BaseModel):
    requestId: int
    status: str
