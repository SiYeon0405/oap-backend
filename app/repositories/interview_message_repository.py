from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.analysis_request import AnalysisRequest
from app.models.interview_message import InterviewMessage


class InterviewMessageRepository:
    def find_analysis_request(
        self,
        session: Session,
        request_id: int,
    ) -> AnalysisRequest | None:
        return session.get(AnalysisRequest, request_id)

    def find_messages(
        self,
        session: Session,
        request_id: int,
    ) -> list[InterviewMessage]:
        return (
            session.query(InterviewMessage)
            .filter(InterviewMessage.analysis_request_id == request_id)
            .order_by(InterviewMessage.message_order.asc())
            .all()
        )

    def find_max_message_order(self, session: Session, request_id: int) -> int | None:
        return (
            session.query(func.max(InterviewMessage.message_order))
            .filter(InterviewMessage.analysis_request_id == request_id)
            .scalar()
        )

    def save_message(
        self,
        session: Session,
        message: InterviewMessage,
    ) -> InterviewMessage:
        session.add(message)
        session.commit()
        session.refresh(message)
        return message
