from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.models.base import Base


class RetrievalRun(Base):
    __tablename__ = "retrieval_runs"

    id = Column(Integer, primary_key=True)
    analysis_request_id = Column(
        Integer,
        ForeignKey("analysis_requests.id", ondelete="CASCADE"),
        nullable=False,
    )
    analysis_report_id = Column(
        Integer,
        ForeignKey("analysis_reports.id", ondelete="SET NULL"),
        nullable=True,
    )
    query = Column(Text, nullable=False)
    retrieval_method = Column(String(30), nullable=False)
    top_k = Column(Integer, nullable=False)
    embedding_model = Column(String(100), nullable=True)
    config_snapshot = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    evidences = relationship(
        "RetrievalEvidence",
        back_populates="retrieval_run",
        cascade="all, delete-orphan",
    )


class RetrievalEvidence(Base):
    __tablename__ = "retrieval_evidences"

    id = Column(Integer, primary_key=True)
    retrieval_run_id = Column(
        Integer,
        ForeignKey("retrieval_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_id_snapshot = Column(BigInteger, nullable=False)
    chunk_index_snapshot = Column(Integer, nullable=False)
    content_snapshot = Column(Text, nullable=False)
    metadata_snapshot = Column(JSONB, nullable=False)
    score_snapshot = Column(JSONB, nullable=False)
    rank = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    retrieval_run = relationship("RetrievalRun", back_populates="evidences")
