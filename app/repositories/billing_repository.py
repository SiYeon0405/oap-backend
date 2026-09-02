from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.billing import (
    BillingMethod,
    BillingRegistrationSession,
    Payment,
    Subscription,
)


class BillingRepository:
    def add_billing_method(
        self,
        session: Session,
        billing_method: BillingMethod,
    ) -> BillingMethod:
        session.add(billing_method)
        return billing_method

    def get_active_billing_method_by_user_id(
        self,
        session: Session,
        user_id: int,
    ) -> BillingMethod | None:
        return session.scalar(
            select(BillingMethod)
            .where(
                BillingMethod.user_id == user_id,
                BillingMethod.is_active.is_(True),
            )
            .order_by(BillingMethod.created_at.desc(), BillingMethod.id.desc())
            .limit(1)
        )

    def deactivate_billing_methods_by_user_id(
        self,
        session: Session,
        user_id: int,
        updated_at: datetime,
    ) -> int:
        result = session.execute(
            update(BillingMethod)
            .where(
                BillingMethod.user_id == user_id,
                BillingMethod.is_active.is_(True),
            )
            .values(is_active=False, updated_at=updated_at)
            .execution_options(synchronize_session="fetch")
        )
        return result.rowcount

    def list_active_billing_methods_by_user_id(
        self,
        session: Session,
        user_id: int,
    ) -> list[BillingMethod]:
        return session.scalars(
            select(BillingMethod)
            .where(
                BillingMethod.user_id == user_id,
                BillingMethod.is_active.is_(True),
            )
            .order_by(BillingMethod.created_at.asc(), BillingMethod.id.asc())
        ).all()

    def add_subscription(
        self,
        session: Session,
        subscription: Subscription,
    ) -> Subscription:
        session.add(subscription)
        return subscription

    def get_subscription_by_id(
        self,
        session: Session,
        subscription_id: int,
    ) -> Subscription | None:
        return session.get(Subscription, subscription_id)

    def get_latest_subscription_by_user_id(
        self,
        session: Session,
        user_id: int,
    ) -> Subscription | None:
        return session.scalar(
            select(Subscription)
            .where(Subscription.user_id == user_id)
            .order_by(Subscription.created_at.desc(), Subscription.id.desc())
            .limit(1)
        )

    def update_subscription_timestamp(
        self,
        session: Session,
        subscription: Subscription,
        updated_at: datetime,
    ) -> Subscription:
        subscription.updated_at = updated_at
        session.add(subscription)
        return subscription

    def add_payment(
        self,
        session: Session,
        payment: Payment,
    ) -> Payment:
        session.add(payment)
        return payment

    def get_payment_by_order_id(
        self,
        session: Session,
        order_id: str,
    ) -> Payment | None:
        return session.scalar(
            select(Payment).where(Payment.order_id == order_id).limit(1)
        )

    def get_payment_by_id(
        self,
        session: Session,
        payment_id: int,
    ) -> Payment | None:
        return session.get(Payment, payment_id)

    def update_payment_timestamp(
        self,
        session: Session,
        payment: Payment,
        updated_at: datetime,
    ) -> Payment:
        payment.updated_at = updated_at
        session.add(payment)
        return payment

    def add_registration_session(
        self,
        session: Session,
        registration_session: BillingRegistrationSession,
    ) -> BillingRegistrationSession:
        session.add(registration_session)
        return registration_session

    def expire_pending_registration_sessions_by_user_id(
        self,
        session: Session,
        user_id: int,
        updated_at: datetime,
    ) -> int:
        result = session.execute(
            update(BillingRegistrationSession)
            .where(
                BillingRegistrationSession.user_id == user_id,
                BillingRegistrationSession.status == "PENDING",
            )
            .values(status="EXPIRED", updated_at=updated_at)
            .execution_options(synchronize_session="fetch")
        )
        return result.rowcount

    def claim_pending_registration_session(
        self,
        session: Session,
        user_id: int,
        customer_key: str,
        now: datetime,
    ) -> BillingRegistrationSession | None:
        return session.scalar(
            update(BillingRegistrationSession)
            .where(
                BillingRegistrationSession.user_id == user_id,
                BillingRegistrationSession.customer_key == customer_key,
                BillingRegistrationSession.status == "PENDING",
                BillingRegistrationSession.expires_at > now,
            )
            .values(status="PROCESSING", updated_at=now)
            .returning(BillingRegistrationSession)
            .execution_options(synchronize_session="fetch")
        )

    def complete_registration_session(
        self,
        session: Session,
        registration_session_id: int,
        completed_at: datetime,
    ) -> bool:
        result = session.execute(
            update(BillingRegistrationSession)
            .where(
                BillingRegistrationSession.id == registration_session_id,
                BillingRegistrationSession.status == "PROCESSING",
            )
            .values(
                status="COMPLETED",
                completed_at=completed_at,
                updated_at=completed_at,
            )
            .execution_options(synchronize_session="fetch")
        )
        return result.rowcount == 1

    def fail_registration_session(
        self,
        session: Session,
        registration_session_id: int,
        updated_at: datetime,
    ) -> bool:
        result = session.execute(
            update(BillingRegistrationSession)
            .where(
                BillingRegistrationSession.id == registration_session_id,
                BillingRegistrationSession.status == "PROCESSING",
            )
            .values(status="FAILED", updated_at=updated_at)
            .execution_options(synchronize_session="fetch")
        )
        return result.rowcount == 1
