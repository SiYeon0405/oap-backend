from fastapi import APIRouter, Depends

from app.api.auth import get_current_user
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
def get_interview(requestId: int, current_user=Depends(get_current_user)):
    return InterviewMessageService().get_interview(requestId, current_user.id)


@router.post("", response_model=InterviewAnswerResponse)
def save_answer(
    requestId: int,
    request: InterviewAnswerRequest,
    current_user=Depends(get_current_user),
):
    return InterviewMessageService().save_answer(requestId, request, current_user.id)
