"""add billing tables

Revision ID: 20260902_billing_tables
Revises: 20260824_admin_read
"""

from alembic import op
import sqlalchemy as sa


revision = "20260902_billing_tables"
down_revision = "20260824_admin_read"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "billing_methods",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("customer_key", sa.String(), nullable=False),
        sa.Column("billing_key_encrypted", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False, server_default=sa.text("'TOSS'")),
        sa.Column("card_company", sa.String(), nullable=True),
        sa.Column("card_number_masked", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("customer_key", name="uq_billing_methods_customer_key"),
    )
    op.create_index("ix_billing_methods_user_id", "billing_methods", ["user_id"])

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("billing_method_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("trial_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_period_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_billing_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('TRIALING','ACTIVE','PAST_DUE','CANCELED')",
            name="ck_subscriptions_status",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["billing_method_id"],
            ["billing_methods.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_subscriptions_user_id", "subscriptions", ["user_id"])
    op.create_index(
        "ix_subscriptions_billing_method_id",
        "subscriptions",
        ["billing_method_id"],
    )
    op.create_index("ix_subscriptions_status", "subscriptions", ["status"])
    op.create_index(
        "ix_subscriptions_next_billing_at",
        "subscriptions",
        ["next_billing_at"],
    )

    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subscription_id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.String(), nullable=False),
        sa.Column("payment_key", sa.String(), nullable=True),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False, server_default=sa.text("'KRW'")),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("failure_code", sa.String(), nullable=True),
        sa.Column(
            "failure_message",
            sa.Text(),
            nullable=True,
            comment="Sanitized summary only; never store raw Toss responses or sensitive data.",
        ),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
        sa.CheckConstraint(
            "status IN ('PENDING','PROCESSING','SUCCEEDED','FAILED','CANCELED')",
            name="ck_payments_status",
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["subscriptions.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("order_id", name="uq_payments_order_id"),
    )
    op.create_index("ix_payments_subscription_id", "payments", ["subscription_id"])
    op.create_index("ix_payments_status", "payments", ["status"])
    op.create_index("ix_payments_created_at", "payments", ["created_at"])

    op.create_table(
        "billing_registration_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("customer_key", sa.String(length=50), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('PENDING','PROCESSING','COMPLETED','EXPIRED','FAILED')",
            name="ck_billing_registration_sessions_status",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "customer_key",
            name="uq_billing_registration_sessions_customer_key",
        ),
    )
    op.create_index(
        "ix_billing_registration_sessions_user_id",
        "billing_registration_sessions",
        ["user_id"],
    )
    op.create_index(
        "ix_billing_registration_sessions_status",
        "billing_registration_sessions",
        ["status"],
    )
    op.create_index(
        "ix_billing_registration_sessions_expires_at",
        "billing_registration_sessions",
        ["expires_at"],
    )
    op.create_index(
        "ix_billing_registration_sessions_user_status",
        "billing_registration_sessions",
        ["user_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_billing_registration_sessions_user_status",
        table_name="billing_registration_sessions",
    )
    op.drop_index(
        "ix_billing_registration_sessions_expires_at",
        table_name="billing_registration_sessions",
    )
    op.drop_index(
        "ix_billing_registration_sessions_status",
        table_name="billing_registration_sessions",
    )
    op.drop_index(
        "ix_billing_registration_sessions_user_id",
        table_name="billing_registration_sessions",
    )
    op.drop_table("billing_registration_sessions")
    op.drop_table("payments")
    op.drop_table("subscriptions")
    op.drop_table("billing_methods")
