from fastapi import APIRouter, BackgroundTasks, Depends, Path, status

from app.api.auth import get_current_user
from app.database.session import get_session
from app.schemas.analysis_request import (
    AnalysisRequestCreate,
    AnalysisRequestCreateResponse,
    AnalysisRequestNaverKeywordsResponse,
    NaverKeywordResponse,
)
from app.repositories.keyword_repository import KeywordRepository
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


@router.get(
    "/{requestId}/naver-keywords",
    response_model=AnalysisRequestNaverKeywordsResponse,
)
def get_naver_keywords(
    request_id: int = Path(alias="requestId"),
    current_user=Depends(get_current_user),
):
    with get_session() as session:
        analysis_request = AnalysisRequestService.get_owned_or_404(
            session,
            request_id,
            current_user.id,
        )
        rows = KeywordRepository().find_metrics_by_analysis_request(session, request_id)
        return AnalysisRequestNaverKeywordsResponse(
            requestId=request_id,
            collectionStatus=analysis_request.keyword_collection_status,
            keywords=[
                NaverKeywordResponse(
                    keyword=keyword.keyword,
                    keywordRaw=keyword.keyword_raw,
                    seedType=metric.seed_type,
                    pcCountRaw=metric.pc_count_raw,
                    mobileCountRaw=metric.mobile_count_raw,
                    pcCount=metric.pc_count,
                    mobileCount=metric.mobile_count,
                    totalCount=metric.total_count,
                    competition=metric.comp_idx,
                    source=metric.source,
                    collectedAt=metric.collected_at,
                )
                for metric, keyword in rows
            ],
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
