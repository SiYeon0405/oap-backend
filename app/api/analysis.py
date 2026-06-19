from fastapi import APIRouter

from app.schemas.analysis_report import AnalysisStartResponse
from app.services.analysis_report_service import AnalysisReportService

router = APIRouter(
    prefix="/api/v1/analysis-requests/{requestId}/analyze",
    tags=["analysis"],
)


@router.post("", response_model=AnalysisStartResponse)
def start_analysis(requestId: int):
    return AnalysisReportService().start_analysis(requestId)
