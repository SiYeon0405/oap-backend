from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, text

from app.models.base import Base


class RefreshTokenSession(Base):
    __tablename__ = "refresh_token_sessions"
    __table_args__ = (
        Index("ix_refresh_token_sessions_user_id", "user_id"),
        Index("ix_refresh_token_sessions_token_family", "token_family"),
        Index("ix_refresh_token_sessions_expires_at", "expires_at"),
        Index("ix_refresh_token_sessions_revoked_at", "revoked_at"),
        Index(
            "ix_refresh_token_sessions_user_id_revoked_at",
            "user_id",
            "revoked_at",
        ),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash = Column(String, nullable=False, unique=True)
    token_family = Column(String, nullable=False)
    jti = Column(String, nullable=False, unique=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    replaced_by_jti = Column(String, nullable=True)
    revoke_reason = Column(String, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
