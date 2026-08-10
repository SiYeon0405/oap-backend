from fastapi import APIRouter, BackgroundTasks, Depends, Path, status

from app.api.auth import get_current_user
from app.database.session import get_session
from app.schemas.analysis_request import (
    AnalysisRequestCreate,
    AnalysisRequestCreateResponse,
)
from app.schemas.analysis_report import AnalysisStartResponse
from app.services.analysis_report_service import AnalysisReportService
from app.services.analysis_request_service import AnalysisRequestService

router = APIRouter(prefix="/api/v1/analysis-requests", tags=["analysis-requests"])


@router.post(
    "",
    response_model=AnalysisRequestCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_analysis_request(
    request: AnalysisRequestCreate,
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_user),
):
    service = AnalysisRequestService()
    analysis_request = service.create(request, current_user.id)
    background_tasks.add_task(
        service.collect_keywords,
        analysis_request.id,
        analysis_request.service_name,
        analysis_request.industry,
        analysis_request.one_line_description,
    )
    return AnalysisRequestCreateResponse(
        requestId=analysis_request.id,
        status=analysis_request.status,
    )


@router.post(
    "/{requestId}/analyze",
    response_model=AnalysisStartResponse,
    status_code=status.HTTP_200_OK,
)
def analyze_request(
    request_id: int = Path(alias="requestId"),
    current_user=Depends(get_current_user),
):
    with get_session() as session:
        AnalysisRequestService.get_owned_or_404(
            session,
            request_id,
            current_user.id,
        )
    return AnalysisReportService().start_analysis(request_id)
