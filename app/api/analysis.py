from fastapi import APIRouter, Depends, Query, Response, status

from app.api.auth import get_current_user
from app.database.session import get_session
from app.schemas.analysis_report import AnalysisReportListResponse, AnalysisReportResponse
from app.schemas.report_citation import ReportCitationsResponse
from app.services.analysis_report_service import AnalysisReportService
from app.services.analysis_request_service import AnalysisRequestService

router = APIRouter(
    prefix="/api/v1/analysis-requests/{requestId}",
    tags=["analysis"],
)

reports_router = APIRouter(prefix="/api/v1/reports", tags=["reports"])


@reports_router.get("", response_model=AnalysisReportListResponse)
def get_reports(
    page: int = Query(default=0, ge=0),
    size: int = Query(default=20, ge=1, le=100),
    current_user=Depends(get_current_user),
):
    return AnalysisReportService().get_reports(current_user.id, page, size)


@reports_router.delete("/{requestId}", status_code=status.HTTP_204_NO_CONTENT)
def delete_report(requestId: int, current_user=Depends(get_current_user)):
    AnalysisReportService().delete_report(requestId, current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
