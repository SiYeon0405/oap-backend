from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)

from app.models.base import Base


class BillingMethod(Base):
    __tablename__ = "billing_methods"
    __table_args__ = (
        UniqueConstraint("customer_key", name="uq_billing_methods_customer_key"),
        Index("ix_billing_methods_user_id", "user_id"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    customer_key = Column(String, nullable=False)
    billing_key_encrypted = Column(Text, nullable=False)
    provider = Column(
        String,
        nullable=False,
        default="TOSS",
        server_default=text("'TOSS'"),
    )
    card_company = Column(String, nullable=True)
    card_number_masked = Column(String, nullable=True)
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('TRIALING','ACTIVE','PAST_DUE','CANCELED')",
            name="ck_subscriptions_status",
        ),
        Index("ix_subscriptions_user_id", "user_id"),
        Index("ix_subscriptions_billing_method_id", "billing_method_id"),
        Index("ix_subscriptions_status", "status"),
        Index("ix_subscriptions_next_billing_at", "next_billing_at"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    billing_method_id = Column(
        Integer,
        ForeignKey("billing_methods.id", ondelete="SET NULL"),
        nullable=True,
    )
    status = Column(String, nullable=False)
    trial_started_at = Column(DateTime(timezone=True), nullable=False)
    trial_ends_at = Column(DateTime(timezone=True), nullable=False)
    current_period_started_at = Column(DateTime(timezone=True), nullable=True)
    current_period_ends_at = Column(DateTime(timezone=True), nullable=True)
    next_billing_at = Column(DateTime(timezone=True), nullable=True)
    canceled_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("order_id", name="uq_payments_order_id"),
        CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
        CheckConstraint(
            "status IN ('PENDING','PROCESSING','SUCCEEDED','FAILED','CANCELED')",
            name="ck_payments_status",
        ),
        Index("ix_payments_subscription_id", "subscription_id"),
        Index("ix_payments_status", "status"),
        Index("ix_payments_created_at", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    subscription_id = Column(
        Integer,
        ForeignKey("subscriptions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    order_id = Column(String, nullable=False)
    payment_key = Column(String, nullable=True)
    amount = Column(Integer, nullable=False)
    currency = Column(
        String,
        nullable=False,
        default="KRW",
        server_default=text("'KRW'"),
    )
    status = Column(String, nullable=False)
    failure_code = Column(String, nullable=True)
    failure_message = Column(
        Text,
        nullable=True,
        comment="Sanitized summary only; never store raw Toss responses or sensitive data.",
    )
    requested_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    approved_at = Column(DateTime(timezone=True), nullable=True)
    failed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class BillingRegistrationSession(Base):
    __tablename__ = "billing_registration_sessions"
    __table_args__ = (
        UniqueConstraint(
            "customer_key",
            name="uq_billing_registration_sessions_customer_key",
        ),
        CheckConstraint(
            "status IN ('PENDING','PROCESSING','COMPLETED','EXPIRED','FAILED')",
            name="ck_billing_registration_sessions_status",
        ),
        Index("ix_billing_registration_sessions_user_id", "user_id"),
        Index("ix_billing_registration_sessions_status", "status"),
        Index("ix_billing_registration_sessions_expires_at", "expires_at"),
        Index(
            "ix_billing_registration_sessions_user_status",
            "user_id",
            "status",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    customer_key = Column(String(50), nullable=False)
    status = Column(
        String(20),
        nullable=False,
        server_default=text("'PENDING'"),
    )
    expires_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
