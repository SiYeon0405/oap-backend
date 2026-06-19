from fastapi import APIRouter

from app.schemas.interview_message import (
    InterviewAnswerRequest,
    InterviewAnswerResponse,
    InterviewMessagesResponse,
)
from app.services.interview_message_service import InterviewMessageService

router = APIRouter(
    prefix="/api/v1/analysis-requests/{requestId}/interview",
    tags=["interview"],
)


@router.get("", response_model=InterviewMessagesResponse)
def get_interview(requestId: int):
    return InterviewMessageService().get_interview(requestId)


@router.post("", response_model=InterviewAnswerResponse)
def save_answer(requestId: int, request: InterviewAnswerRequest):
    return InterviewMessageService().save_answer(requestId, request)
