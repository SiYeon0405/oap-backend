from fastapi import HTTPException, status

from app.database.session import get_session
from app.repositories.interview_message_repository import InterviewMessageRepository
from app.schemas.interview_message import (
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
