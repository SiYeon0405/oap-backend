"""add analytics event collection tables

Revision ID: 20260820_analytics_events
Revises: 20260815_nullable_evidence_docs
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260820_analytics_events"
down_revision = "20260815_nullable_evidence_docs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analytics_sessions",
        sa.Column("session_id", sa.String(128), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("entry_page", sa.String(64), nullable=True),
        sa.Column("device_type", sa.String(32), nullable=True),
        sa.Column("browser_family", sa.String(64), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_analytics_sessions_user_activity",
        "analytics_sessions",
        ["user_id", sa.text("last_activity_at DESC")],
    )
    op.create_index(
        "ix_analytics_sessions_last_activity",
        "analytics_sessions",
        ["last_activity_at"],
    )

    op.create_table(
        "analytics_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("event_name", sa.String(64), nullable=False),
        sa.Column("event_version", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("session_id", sa.String(128), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("page_name", sa.String(64), nullable=True),
        sa.Column("path_template", sa.String(200), nullable=True),
        sa.Column("target_type", sa.String(32), nullable=True),
        sa.Column("target_id", sa.String(128), nullable=True),
        sa.Column("result", sa.String(16), nullable=True),
        sa.Column("properties", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.CheckConstraint("event_version >= 1", name="ck_analytics_events_version"),
        sa.CheckConstraint("result IN ('success', 'failure') OR result IS NULL", name="ck_analytics_events_result"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_analytics_events_occurred_name", "analytics_events", ["occurred_at", "event_name"])
    op.create_index("ix_analytics_events_user_occurred", "analytics_events", ["user_id", sa.text("occurred_at DESC")])
    op.create_index("ix_analytics_events_session_occurred", "analytics_events", ["session_id", "occurred_at"])


def downgrade() -> None:
    op.drop_table("analytics_events")
    op.drop_table("analytics_sessions")
