from fastapi import HTTPException, status
from sqlalchemy import select

from app.database.session import get_session
from app.models.analysis_request import AnalysisRequest
from app.models.interview_message import InterviewMessage
from app.repositories.analysis_request_repository import AnalysisRequestRepository
from app.repositories.interview_message_repository import InterviewMessageRepository
from app.schemas.analysis_request import AnalysisRequestCreate


class AnalysisRequestService:
    def __init__(
        self,
        repository: AnalysisRequestRepository | None = None,
        interview_repository: InterviewMessageRepository | None = None,
    ):
        self.repository = repository or AnalysisRequestRepository()
        self.interview_repository = interview_repository or InterviewMessageRepository()

    @staticmethod
    def get_owned_or_404(session, request_id: int, user_id: int) -> AnalysisRequest:
        analysis_request = session.scalar(
            select(AnalysisRequest).where(
                AnalysisRequest.id == request_id,
                AnalysisRequest.user_id == user_id,
            )
        )
        if analysis_request is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="analysis request not found",
            )
        return analysis_request

    def create(
        self,
        request: AnalysisRequestCreate,
        user_id: int,
    ) -> AnalysisRequest:
        analysis_request = AnalysisRequest(
            user_id=user_id,
            service_name=request.serviceName,
            one_line_description=request.oneLineDescription,
            industry=request.industry,
            main_question=request.mainQuestion,
            status="INTERVIEWING",
            interview_completed=False,
        )

        with get_session() as session:
            saved_analysis_request = self.repository.save(session, analysis_request)
            first_question = self.generate_first_question(
                saved_analysis_request.service_name,
                saved_analysis_request.one_line_description,
                saved_analysis_request.industry,
                saved_analysis_request.main_question,
            )
            self.interview_repository.save_message(
                session,
                InterviewMessage(
                    analysis_request_id=saved_analysis_request.id,
                    role="AI",
                    content=first_question,
                    message_order=1,
                ),
            )
            session.refresh(saved_analysis_request)
            return saved_analysis_request

    # TODO: Replace rule-based question generation with OpenAI/AI chatbot call.
    def generate_first_question(
        self,
        service_name: str,
        one_line_description: str,
        industry: str,
        main_question: str,
    ) -> str:
        return (
            "누가 이 서비스를 가장 많이 쓸까요? "
            "(예: 혼자 가게를 운영하는 사장님) "
            "잘 모르겠으면 '잘 모르겠어요'라고 답해도 됩니다."
        )
