from fastapi import APIRouter, Depends

from app.api.auth import get_current_user
from app.database.session import get_session
from app.schemas.analysis_report import AnalysisReportResponse
from app.schemas.report_citation import ReportCitationsResponse
from app.services.analysis_report_service import AnalysisReportService
from app.services.analysis_request_service import AnalysisRequestService

router = APIRouter(
    prefix="/api/v1/analysis-requests/{requestId}",
    tags=["analysis"],
)


@router.get("/report", response_model=AnalysisReportResponse)
def get_report(requestId: int, current_user=Depends(get_current_user)):
    with get_session() as session:
        AnalysisRequestService.get_owned_or_404(
            session,
            requestId,
            current_user.id,
        )
    return AnalysisReportService().get_report(requestId)


@router.get("/report/citations", response_model=ReportCitationsResponse)
def get_report_citations(requestId: int, current_user=Depends(get_current_user)):
    with get_session() as session:
        AnalysisRequestService.get_owned_or_404(
            session,
            requestId,
            current_user.id,
        )
    return AnalysisReportService().get_report_citations(requestId)
