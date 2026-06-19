from sqlalchemy import Column, DateTime, Integer, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class AnalysisReport(Base):
    __tablename__ = "analysis_reports"

    id = Column(Integer, primary_key=True)
    analysis_request_id = Column(Integer, nullable=False)
    service_summary = Column(JSONB, nullable=False)
    market_analysis = Column(JSONB, nullable=False)
    competitor_analysis = Column(JSONB, nullable=False)
    target_customer_analysis = Column(JSONB, nullable=False)
    marketing_strategy = Column(JSONB, nullable=False)
    platform_recommendation = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
