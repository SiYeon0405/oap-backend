from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)

from app.models.base import Base


class MarketingConsent(Base):
    __tablename__ = "marketing_consents"
    __table_args__ = (
        Index(
            "ix_marketing_consents_user_occurred_id",
            "user_id",
            "occurred_at",
            "id",
        ),
    )

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_version = Column(String(50), nullable=False)
    is_agreed = Column(Boolean, nullable=False)
    occurred_at = Column(DateTime(timezone=True), nullable=False)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(512), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
