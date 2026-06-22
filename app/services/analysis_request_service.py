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
        return "서비스의 주요 기능을 조금 더 구체적으로 알려주세요."
