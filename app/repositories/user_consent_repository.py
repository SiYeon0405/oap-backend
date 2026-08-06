from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.marketing_consent import MarketingConsent
from app.models.user_consent import UserConsent


class UserConsentRepository:
    def add_all(self, session: Session, consents: list[UserConsent]) -> None:
        session.add_all(consents)

    def find_history(self, session: Session, user_id: int) -> list[UserConsent]:
        return session.scalars(
            select(UserConsent)
            .where(UserConsent.user_id == user_id)
            .order_by(UserConsent.occurred_at.desc(), UserConsent.id.desc())
        ).all()

    def find_latest(
        self,
        session: Session,
        user_id: int,
        consent_type: str,
    ) -> UserConsent | None:
        return session.scalar(
            select(UserConsent)
            .where(
                UserConsent.user_id == user_id,
                UserConsent.consent_type == consent_type,
            )
            .order_by(UserConsent.occurred_at.desc(), UserConsent.id.desc())
            .limit(1)
        )

    def add(self, session: Session, consent: UserConsent) -> None:
        session.add(consent)


class MarketingConsentRepository:
    def add(self, session: Session, consent: MarketingConsent) -> None:
        session.add(consent)

    def find_history(
        self, session: Session, user_id: int
    ) -> list[MarketingConsent]:
        return session.scalars(
            select(MarketingConsent)
            .where(MarketingConsent.user_id == user_id)
            .order_by(
                MarketingConsent.occurred_at.desc(),
                MarketingConsent.id.desc(),
            )
        ).all()

    def find_latest(
        self, session: Session, user_id: int
    ) -> MarketingConsent | None:
        return session.scalar(
            select(MarketingConsent)
            .where(MarketingConsent.user_id == user_id)
            .order_by(
                MarketingConsent.occurred_at.desc(),
                MarketingConsent.id.desc(),
            )
            .limit(1)
        )
