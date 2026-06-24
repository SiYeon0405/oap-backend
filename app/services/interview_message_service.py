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
from app.services.analysis_report_service import AnalysisReportService


class InterviewMessageService:
    QUESTION_CANDIDATES = (
        "서비스의 주요 기능을 조금 더 구체적으로 알려주세요.",
        "예상 고객은 누구인가요?",
        "현재 유료 서비스인가요?",
        "현재 판매 또는 운영 방식은 무엇인가요?",
        "가장 검증하고 싶은 마케팅 채널은 무엇인가요?",
        "현재 경쟁 서비스나 참고하고 있는 서비스가 있나요?",
    )
    FALLBACK_QUESTION = "추가로 확인하고 싶은 내용이 있다면 자유롭게 말씀해주세요."

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
            if analysis_request.interview_completed or analysis_request.status != "INTERVIEWING":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="interview is already completed",
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
            user_answer_count = sum(1 for message in messages if message.role == "USER")
            if user_answer_count >= 5:
                should_start_analysis = True
            else:
                should_start_analysis = False
                next_question = self.generate_next_question(analysis_request, messages)
                max_message_order = self.repository.find_max_message_order(session, request_id)
                ai_message = InterviewMessage(
                    analysis_request_id=request_id,
                    role="AI",
                    content=next_question,
                    message_order=(max_message_order or 0) + 1,
                )
                self.repository.save_message(session, ai_message)
                response_status = analysis_request.status
                response_interview_completed = analysis_request.interview_completed

        if should_start_analysis:
            analysis_result = AnalysisReportService().start_analysis(request_id)
            return InterviewAnswerResponse(
                nextQuestion=None,
                status=analysis_result.status,
                interviewCompleted=True,
            )

        return InterviewAnswerResponse(
            nextQuestion=ai_message.content,
            status=response_status,
            interviewCompleted=response_interview_completed,
        )

    # TODO: Replace rule-based question generation with OpenAI/AI chatbot call.
    def generate_next_question(
        self,
        analysis_request,
        messages: list[InterviewMessage],
    ) -> str:
        ai_questions = [message.content for message in messages if message.role == "AI"]
        ai_question_count = len(ai_questions)

        for question in self.QUESTION_CANDIDATES[ai_question_count:]:
            if question not in ai_questions:
                return question

        return self.FALLBACK_QUESTION
