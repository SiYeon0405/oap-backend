from fastapi import APIRouter, status

from app.schemas.analysis_request import (
    AnalysisRequestCreate,
    AnalysisRequestCreateResponse,
)
from app.services.analysis_request_service import AnalysisRequestService

router = APIRouter(prefix="/api/v1/analysis-requests", tags=["analysis-requests"])


@router.post(
    "",
    response_model=AnalysisRequestCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_analysis_request(request: AnalysisRequestCreate):
    analysis_request = AnalysisRequestService().create(request)
    return AnalysisRequestCreateResponse(
        requestId=analysis_request.id,
        status=analysis_request.status,
    )
