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


class UserConsent(Base):
    __tablename__ = "user_consents"
    __table_args__ = (
        Index(
            "ix_user_consents_user_type_occurred_id",
            "user_id",
            "consent_type",
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
    consent_type = Column(String(20), nullable=False)
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
