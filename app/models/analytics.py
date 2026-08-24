from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from app.models.base import Base


class AnalyticsEvent(Base):
    __tablename__ = "analytics_events"
    __table_args__ = (
        CheckConstraint("event_version >= 1", name="ck_analytics_events_version"),
        CheckConstraint(
            "result IN ('success', 'failure') OR result IS NULL",
            name="ck_analytics_events_result",
        ),
        Index("ix_analytics_events_occurred_name", "occurred_at", "event_name"),
        Index(
            "ix_analytics_events_user_occurred",
            "user_id",
            text("occurred_at DESC"),
        ),
        Index("ix_analytics_events_session_occurred", "session_id", "occurred_at"),
        Index("ix_analytics_events_user_cursor", "user_id", text("occurred_at DESC"), "event_id"),
        Index("ix_analytics_events_session_cursor", "session_id", text("occurred_at DESC"), "event_id"),
        Index("ix_analytics_events_result_occurred", "result", text("occurred_at DESC")),
    )

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    event_id = Column(Uuid, nullable=False, unique=True)
    event_name = Column(String(64), nullable=False)
    event_version = Column(Integer, nullable=False)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    session_id = Column(String(128), nullable=False)
    occurred_at = Column(DateTime(timezone=True), nullable=False)
    received_at = Column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    page_name = Column(String(64), nullable=True)
    path_template = Column(String(200), nullable=True)
    target_type = Column(String(32), nullable=True)
    target_id = Column(String(128), nullable=True)
    result = Column(String(16), nullable=True)
    properties = Column(
        JSONB().with_variant(JSON, "sqlite"),
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )


class AnalyticsSession(Base):
    __tablename__ = "analytics_sessions"
    __table_args__ = (
        Index(
            "ix_analytics_sessions_user_activity",
            "user_id",
            text("last_activity_at DESC"),
        ),
        Index("ix_analytics_sessions_last_activity", "last_activity_at"),
    )

    session_id = Column(String(128), primary_key=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    started_at = Column(DateTime(timezone=True), nullable=False)
    last_activity_at = Column(DateTime(timezone=True), nullable=False)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    entry_page = Column(String(64), nullable=True)
    device_type = Column(String(32), nullable=True)
    browser_family = Column(String(64), nullable=True)


class AnalyticsAdminHourly(Base):
    __tablename__ = "analytics_admin_hourly"
    __table_args__ = (Index("ix_analytics_admin_hourly_bucket", "bucket_start"),)

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    bucket_start = Column(DateTime(timezone=True), nullable=False)
    user_id = Column(Integer, nullable=True)
    session_id = Column(String(128), nullable=False)
    event_name = Column(String(64), nullable=False)
    result = Column(String(16), nullable=True)
    event_count = Column(Integer, nullable=False)


class AnalyticsAdminAggregateState(Base):
    __tablename__ = "analytics_admin_aggregate_state"

    id = Column(Integer, primary_key=True)
    data_through = Column(DateTime(timezone=True), nullable=False)
    refreshed_at = Column(DateTime(timezone=True), nullable=False)
