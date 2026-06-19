from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class InterviewMessage(Base):
    __tablename__ = "interview_messages"

    id = Column(Integer, primary_key=True)
    analysis_request_id = Column(Integer, ForeignKey("analysis_requests.id"), nullable=False)
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    message_order = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
