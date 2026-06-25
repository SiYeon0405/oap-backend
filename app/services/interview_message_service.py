from fastapi import HTTPException, status

from app.ai.interview_question_ai import generate_next_question
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
            if (
                analysis_request.status == "COMPLETED"
                or analysis_request.interview_completed
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="이미 완료된 인터뷰입니다.",
                )

            max_message_order = self.repository.find_max_message_order(session, request_id)
            message = InterviewMessage(
                analysis_request_id=request_id,
                role="USER",
                content=request.answer,
                message_order=(max_message_order or 0) + 1,
            )
            self.repository.save_message(session, message)

            messages = self.repository.find_messages(session, request_id)
            user_answer_count = len(
                [message for message in messages if message.role == "USER"]
            )
            if user_answer_count >= 5:
                analysis_request.status = "COMPLETED"
                analysis_request.interview_completed = True
                session.add(analysis_request)
                session.commit()
                status_value = analysis_request.status
                interview_completed = analysis_request.interview_completed
                return InterviewAnswerResponse(
                    nextQuestion="",
                    status=status_value,
                    interviewCompleted=interview_completed,
                )

            next_question = generate_next_question(analysis_request, messages)
            max_message_order = self.repository.find_max_message_order(session, request_id)
            ai_message = InterviewMessage(
                analysis_request_id=request_id,
                role="AI",
                content=next_question,
                message_order=(max_message_order or 0) + 1,
            )
            self.repository.save_message(session, ai_message)
            status_value = analysis_request.status
            interview_completed = analysis_request.interview_completed

        return InterviewAnswerResponse(
            nextQuestion=ai_message.content,
            status=status_value,
            interviewCompleted=interview_completed,
        )


