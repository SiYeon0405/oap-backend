from pydantic import BaseModel


class AnalysisStartResponse(BaseModel):
    requestId: int
    status: str
