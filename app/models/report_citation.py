from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import relationship

from app.models.base import Base


class ReportCitation(Base):
    __tablename__ = "report_citations"
    __table_args__ = (
        UniqueConstraint(
            "analysis_report_id",
            "section_key",
            "retrieval_evidence_id",
            name="uq_report_citations_report_section_evidence",
        ),
    )

    id = Column(Integer, primary_key=True)
    analysis_report_id = Column(
        Integer,
        ForeignKey("analysis_reports.id", ondelete="CASCADE"),
        nullable=False,
    )
    retrieval_evidence_id = Column(
        Integer,
        ForeignKey("retrieval_evidences.id", ondelete="CASCADE"),
        nullable=False,
    )
    section_key = Column(String(50), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    retrieval_evidence = relationship("RetrievalEvidence")
