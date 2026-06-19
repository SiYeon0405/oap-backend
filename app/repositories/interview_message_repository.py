from sqlalchemy.orm import Session

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
