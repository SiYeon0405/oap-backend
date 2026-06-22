from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class AnalysisRequest(Base):
    __tablename__ = "analysis_requests"

    id = Column(Integer, primary_key=True)
    service_name = Column(String, nullable=False)
    one_line_description = Column(String, nullable=False)
    industry = Column(String, nullable=False)
    main_question = Column(Text, nullable=False)
    status = Column(String, nullable=False)
    interview_completed = Column(Boolean, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
