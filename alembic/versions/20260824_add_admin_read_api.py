"""add administrator read API support

Revision ID: 20260824_admin_read
Revises: 20260820_admin_auth
"""

from alembic import op
import sqlalchemy as sa


revision = "20260824_admin_read"
down_revision = "20260820_admin_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "analytics_admin_hourly",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("session_id", sa.String(128), nullable=False),
        sa.Column("event_name", sa.String(64), nullable=False),
        sa.Column("result", sa.String(16), nullable=True),
        sa.Column("event_count", sa.Integer(), nullable=False),
    )
    op.create_index("ix_analytics_admin_hourly_bucket", "analytics_admin_hourly", ["bucket_start"])
    op.create_table(
        "analytics_admin_aggregate_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("data_through", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_analytics_events_result_occurred", "analytics_events", ["result", sa.text("occurred_at DESC")])
    op.create_index("ix_analytics_events_user_cursor", "analytics_events", ["user_id", sa.text("occurred_at DESC"), "event_id"])
    op.create_index("ix_analytics_events_session_cursor", "analytics_events", ["session_id", sa.text("occurred_at DESC"), "event_id"])
    op.create_index("ix_admin_audit_logs_occurred_id", "admin_audit_logs", [sa.text("occurred_at DESC"), "id"])


def downgrade() -> None:
    op.drop_index("ix_admin_audit_logs_occurred_id", table_name="admin_audit_logs")
    op.drop_index("ix_analytics_events_session_cursor", table_name="analytics_events")
    op.drop_index("ix_analytics_events_user_cursor", table_name="analytics_events")
    op.drop_index("ix_analytics_events_result_occurred", table_name="analytics_events")
    op.drop_table("analytics_admin_aggregate_state")
    op.drop_index("ix_analytics_admin_hourly_bucket", table_name="analytics_admin_hourly")
    op.drop_table("analytics_admin_hourly")
    op.drop_column("users", "last_login_at")
