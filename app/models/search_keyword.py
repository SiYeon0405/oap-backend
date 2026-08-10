from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, text

from app.models.base import Base


class Keyword(Base):
    __tablename__ = "keywords"

    id = Column(Integer, primary_key=True)
    keyword = Column(String, nullable=False, unique=True)
    keyword_raw = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class KeywordMetric(Base):
    __tablename__ = "keyword_metrics"
    __table_args__ = (
        Index("ix_keyword_metrics_keyword_collected", "keyword_id", text("collected_at DESC")),
    )

    id = Column(Integer, primary_key=True)
    keyword_id = Column(Integer, ForeignKey("keywords.id"), nullable=False)
    pc_count_raw = Column(String, nullable=False)
    mobile_count_raw = Column(String, nullable=False)
    pc_count = Column(Integer, nullable=False)
    mobile_count = Column(Integer, nullable=False)
    total_count = Column(Integer, nullable=False)
    comp_idx = Column(String)
    source = Column(String, nullable=False, server_default="naver_searchad_keywordstool")
    collected_at = Column(DateTime(timezone=True), nullable=False)


class ReportEvidence(Base):
    __tablename__ = "report_evidences"

    id = Column(Integer, primary_key=True)
    report_id = Column(Integer, ForeignKey("analysis_reports.id", ondelete="CASCADE"), nullable=False)
    metric_id = Column(Integer, ForeignKey("keyword_metrics.id"), nullable=False)
    evidence_no = Column(Integer, nullable=False)
    seed_type = Column(String, nullable=False)
    section = Column(String, nullable=False)
