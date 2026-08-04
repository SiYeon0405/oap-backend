from datetime import datetime, timezone

from app.database.session import get_session
from app.models.user_consent import UserConsent
from app.repositories.user_consent_repository import UserConsentRepository
from app.schemas.auth import ConsentItem, ConsentResponse


CURRENT_CONSENT_DOCUMENT_VERSION = "2.1"
CONSENT_TYPES = ("TERMS", "PRIVACY", "MARKETING")


class UserConsentService:
    def __init__(self, repository: UserConsentRepository | None = None):
        self.repository = repository or UserConsentRepository()

    def add_initial_consents(
        self,
        session,
        user_id: int,
        *,
        terms_agreed: bool,
        privacy_agreed: bool,
        marketing_agreed: bool,
        ip_address: str | None,
        user_agent: str | None,
    ) -> None:
        self.repository.add_all(
            session,
            self.build_initial_consents(
                user_id,
                terms_agreed=terms_agreed,
                privacy_agreed=privacy_agreed,
                marketing_agreed=marketing_agreed,
                ip_address=ip_address,
                user_agent=user_agent,
            ),
        )

    def build_initial_consents(
        self,
        user_id: int,
        *,
        terms_agreed: bool,
        privacy_agreed: bool,
        marketing_agreed: bool,
        ip_address: str | None,
        user_agent: str | None,
    ) -> list[UserConsent]:
        occurred_at = datetime.now(timezone.utc)
        values = {
            "TERMS": terms_agreed,
            "PRIVACY": privacy_agreed,
            "MARKETING": marketing_agreed,
        }
        return [
            self._new_consent(
                user_id,
                consent_type,
                values[consent_type],
                occurred_at,
                ip_address,
                user_agent,
            )
            for consent_type in CONSENT_TYPES
        ]

    def get_consents(self, user_id: int) -> ConsentResponse:
        with get_session() as session:
            history = self.repository.find_history(session, user_id)
        current_by_type = {}
        for consent in history:
            current_by_type.setdefault(consent.consent_type, consent)
        return ConsentResponse(
            current=[self._to_item(value) for value in current_by_type.values()],
            history=[self._to_item(value) for value in history],
        )

    def set_marketing(
        self,
        user_id: int,
        agreed: bool,
        *,
        ip_address: str | None,
        user_agent: str | None,
    ) -> ConsentItem:
        with get_session() as session:
            current = self.repository.find_latest(session, user_id, "MARKETING")
            if current is not None and current.is_agreed == agreed:
                return self._to_item(current)
            consent = self._new_consent(
                user_id,
                "MARKETING",
                agreed,
                datetime.now(timezone.utc),
                ip_address,
                user_agent,
            )
            self.repository.add(session, consent)
            session.commit()
            session.refresh(consent)
            return self._to_item(consent)

    @staticmethod
    def _new_consent(
        user_id: int,
        consent_type: str,
        agreed: bool,
        occurred_at: datetime,
        ip_address: str | None,
        user_agent: str | None,
    ) -> UserConsent:
        return UserConsent(
            user_id=user_id,
            consent_type=consent_type,
            document_version=CURRENT_CONSENT_DOCUMENT_VERSION,
            is_agreed=agreed,
            occurred_at=occurred_at,
            ip_address=ip_address[:45] if ip_address else None,
            user_agent=user_agent[:512] if user_agent else None,
        )

    @staticmethod
    def _to_item(consent: UserConsent) -> ConsentItem:
        return ConsentItem(
            type=consent.consent_type,
            documentVersion=consent.document_version,
            agreed=consent.is_agreed,
            occurredAt=consent.occurred_at,
        )
