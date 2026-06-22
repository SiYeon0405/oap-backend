from fastapi import APIRouter

from app.schemas.analysis_report import AnalysisReportResponse, AnalysisStartResponse
from app.services.analysis_report_service import AnalysisReportService

router = APIRouter(
    prefix="/api/v1/analysis-requests/{requestId}",
    tags=["analysis"],
)


@router.post("/analyze", response_model=AnalysisStartResponse)
def start_analysis(requestId: int):
    return AnalysisReportService().start_analysis(requestId)


@router.get("/report", response_model=AnalysisReportResponse)
def get_report(requestId: int):
    return AnalysisReportService().get_report(requestId)
