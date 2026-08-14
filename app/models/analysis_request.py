from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text, text

from app.models.base import Base


class AnalysisRequest(Base):
    __tablename__ = "analysis_requests"
    __table_args__ = (
        Index("ix_analysis_requests_user_id_created_at", "user_id", "created_at"),
        CheckConstraint(
            "keyword_collection_status IN ('PENDING','COLLECTING','COMPLETED','FAILED')",
            name="ck_analysis_requests_keyword_collection_status",
        ),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    service_name = Column(String, nullable=False)
    one_line_description = Column(String, nullable=False)
    industry = Column(String, nullable=False)
    main_question = Column(Text, nullable=False)
    status = Column(String, nullable=False)
    keyword_collection_status = Column(
        String,
        nullable=False,
        default="PENDING",
        server_default=text("'PENDING'"),
    )
    interview_completed = Column(Boolean, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
