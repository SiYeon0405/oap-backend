from fastapi import APIRouter

from app.schemas.interview_message import InterviewMessagesResponse
from app.services.interview_message_service import InterviewMessageService

router = APIRouter(
    prefix="/api/v1/analysis-requests/{requestId}/interview",
    tags=["interview"],
)


@router.get("", response_model=InterviewMessagesResponse)
def get_interview(requestId: int):
    return InterviewMessageService().get_interview(requestId)
