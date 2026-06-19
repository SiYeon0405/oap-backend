from fastapi import HTTPException, status

from app.database.session import get_session
from app.models.interview_message import InterviewMessage
from app.repositories.interview_message_repository import InterviewMessageRepository
from app.schemas.interview_message import (
    InterviewAnswerRequest,
    InterviewAnswerResponse,
    InterviewMessageResponse,
    InterviewMessagesResponse,
)


class InterviewMessageService:
    def __init__(self, repository: InterviewMessageRepository | None = None):
        self.repository = repository or InterviewMessageRepository()

    def get_interview(self, request_id: int) -> InterviewMessagesResponse:
        with get_session() as session:
            analysis_request = self.repository.find_analysis_request(session, request_id)
            if analysis_request is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="analysis request not found",
                )

            messages = self.repository.find_messages(session, request_id)

            return InterviewMessagesResponse(
                requestId=analysis_request.id,
                status=analysis_request.status,
                messages=[
                    InterviewMessageResponse(role=message.role, content=message.content)
                    for message in messages
                ],
            )

    def save_answer(
        self,
        request_id: int,
        request: InterviewAnswerRequest,
    ) -> InterviewAnswerResponse:
        with get_session() as session:
            analysis_request = self.repository.find_analysis_request(session, request_id)
            if analysis_request is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="analysis request not found",
                )

            max_message_order = self.repository.find_max_message_order(session, request_id)
            message = InterviewMessage(
                analysis_request_id=request_id,
                role="USER",
                content=request.answer,
                message_order=(max_message_order or 0) + 1,
            )
            self.repository.save_message(session, message)

        return InterviewAnswerResponse(nextQuestion=self._generate_next_question())

    def _generate_next_question(self) -> str:
        # TODO: Replace with AI/LangChain question generation
        return "현재 유료 서비스인가요?"
