from app.database.session import get_session
from app.models.analysis_request import AnalysisRequest
from app.repositories.analysis_request_repository import AnalysisRequestRepository
from app.schemas.analysis_request import AnalysisRequestCreate


class AnalysisRequestService:
    def __init__(self, repository: AnalysisRequestRepository | None = None):
        self.repository = repository or AnalysisRequestRepository()

    def create(self, request: AnalysisRequestCreate) -> AnalysisRequest:
        analysis_request = AnalysisRequest(
            service_name=request.serviceName,
            one_line_description=request.oneLineDescription,
            industry=request.industry,
            main_question=request.mainQuestion,
            status="INTERVIEWING",
            interview_completed=False,
        )

        with get_session() as session:
            return self.repository.save(session, analysis_request)
