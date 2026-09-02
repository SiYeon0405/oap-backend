from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import NoReturn
from uuid import uuid4

from sqlalchemy import select

from app.database.session import get_session
from app.models.billing import BillingMethod, BillingRegistrationSession
from app.models.user import User
from app.repositories.billing_repository import BillingRepository
from app.services.billing_security import (
    BillingKeyCipher,
    BillingKeyEncryptionError,
    BillingSecurityConfigurationError,
)
from app.services.toss_billing_client import (
    TossBillingApiError,
    TossBillingClient,
    TossBillingConfigurationError,
    TossBillingResponseError,
    TossBillingTransportError,
    TossBillingValidationError,
)


BILLING_REGISTRATION_TTL_MINUTES = 15


@dataclass(frozen=True)
class BillingRegistrationStartResult:
    customer_key: str = field(repr=False)
    expires_at: datetime


@dataclass(frozen=True)
class BillingRegistrationCompleteResult:
    billing_method_id: int
    card_issuer_code: str | None
    card_number_masked: str | None
    authenticated_at: str
    cleanup_required: bool


class BillingServiceError(RuntimeError):
    message = "Billing service failed"

    def __init__(self):
        super().__init__(self.message)


class BillingUserUnavailableError(BillingServiceError):
    message = "Billing user is unavailable"


class BillingRegistrationUnavailableError(BillingServiceError):
    message = "Billing registration is unavailable"


class BillingRegistrationExpiredOrUsedError(BillingServiceError):
    message = "Billing registration is expired or already used"


class BillingProviderError(BillingServiceError):
    message = "Billing provider request failed"


class BillingPersistenceError(BillingServiceError):
    message = "Billing data could not be saved"


class BillingCompensationError(BillingServiceError):
    message = "Billing compensation requires review"


PROVIDER_ERRORS = (
    TossBillingApiError,
    TossBillingConfigurationError,
    TossBillingResponseError,
    TossBillingTransportError,
    TossBillingValidationError,
)
ENCRYPTION_ERRORS = (
    BillingKeyEncryptionError,
    BillingSecurityConfigurationError,
)


class BillingService:
    def __init__(
        self,
        repository: BillingRepository | None = None,
        billing_client: TossBillingClient | None = None,
        billing_key_cipher: BillingKeyCipher | None = None,
    ):
        self.repository = (
            repository if repository is not None else BillingRepository()
        )
        self.billing_key_cipher = (
            billing_key_cipher
            if billing_key_cipher is not None
            else BillingKeyCipher.from_settings()
        )
        self._owns_billing_client = billing_client is None
        self.billing_client = (
            billing_client
            if billing_client is not None
            else TossBillingClient.from_settings()
        )

    def close(self) -> None:
        if self._owns_billing_client:
            self.billing_client.close()

    def __enter__(self) -> "BillingService":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def start_registration(self, user_id: int) -> BillingRegistrationStartResult:
        now = datetime.now(timezone.utc)
        customer_key = str(uuid4())
        expires_at = now + timedelta(minutes=BILLING_REGISTRATION_TTL_MINUTES)
        with get_session() as session:
            try:
                if self._lock_active_user(session, user_id) is None:
                    raise BillingUserUnavailableError
                self.repository.expire_pending_registration_sessions_by_user_id(
                    session,
                    user_id,
                    now,
                )
                self.repository.add_registration_session(
                    session,
                    BillingRegistrationSession(
                        user_id=user_id,
                        customer_key=customer_key,
                        status="PENDING",
                        expires_at=expires_at,
                    ),
                )
                session.commit()
            except BillingServiceError:
                session.rollback()
                raise
            except Exception:
                session.rollback()
                raise BillingPersistenceError from None
        return BillingRegistrationStartResult(
            customer_key=customer_key,
            expires_at=expires_at,
        )

    def complete_registration(
        self,
        user_id: int,
        customer_key: str,
        auth_key: str,
    ) -> BillingRegistrationCompleteResult:
        if (
            not isinstance(customer_key, str)
            or not customer_key.strip()
            or not isinstance(auth_key, str)
            or not auth_key.strip()
        ):
            raise BillingRegistrationUnavailableError

        registration_session_id = self._claim_registration_session(
            user_id,
            customer_key,
        )
        try:
            issued = self.billing_client.issue_billing_key(auth_key, customer_key)
        except PROVIDER_ERRORS:
            self._mark_registration_failed(registration_session_id)
            raise BillingProviderError from None

        new_billing_key = issued.billing_key
        try:
            encrypted_billing_key = self.billing_key_cipher.encrypt(new_billing_key)
        except ENCRYPTION_ERRORS:
            self._raise_after_compensation(
                new_billing_key,
                registration_session_id,
                BillingPersistenceError,
            )

        saved_at = datetime.now(timezone.utc)
        old_billing_methods: list[tuple[int, str]]
        try:
            with get_session() as session:
                try:
                    if self._lock_active_user(session, user_id) is None:
                        raise BillingUserUnavailableError
                    old_billing_methods = [
                        (method.id, method.billing_key_encrypted)
                        for method in self.repository.list_active_billing_methods_by_user_id(
                            session,
                            user_id,
                        )
                    ]
                    self.repository.deactivate_billing_methods_by_user_id(
                        session,
                        user_id,
                        saved_at,
                    )
                    billing_method = self.repository.add_billing_method(
                        session,
                        BillingMethod(
                            user_id=user_id,
                            customer_key=issued.customer_key,
                            billing_key_encrypted=encrypted_billing_key,
                            provider="TOSS",
                            card_company=issued.card_issuer_code,
                            card_number_masked=issued.card_number_masked,
                            is_active=True,
                        ),
                    )
                    session.flush()
                    if not self.repository.complete_registration_session(
                        session,
                        registration_session_id,
                        saved_at,
                    ):
                        raise BillingPersistenceError
                    billing_method_id = int(billing_method.id)
                    session.commit()
                except BillingServiceError:
                    session.rollback()
                    raise
                except Exception:
                    session.rollback()
                    raise BillingPersistenceError from None
        except BillingUserUnavailableError:
            self._raise_after_compensation(
                new_billing_key,
                registration_session_id,
                BillingUserUnavailableError,
            )
        except BillingPersistenceError:
            self._raise_after_compensation(
                new_billing_key,
                registration_session_id,
                BillingPersistenceError,
            )

        cleanup_required = self._cleanup_old_billing_keys(old_billing_methods)
        return BillingRegistrationCompleteResult(
            billing_method_id=billing_method_id,
            card_issuer_code=issued.card_issuer_code,
            card_number_masked=issued.card_number_masked,
            authenticated_at=issued.authenticated_at,
            cleanup_required=cleanup_required,
        )

    def _claim_registration_session(
        self,
        user_id: int,
        customer_key: str,
    ) -> int:
        now = datetime.now(timezone.utc)
        with get_session() as session:
            try:
                if self._lock_active_user(session, user_id) is None:
                    raise BillingUserUnavailableError
                registration_session = (
                    self.repository.claim_pending_registration_session(
                        session,
                        user_id,
                        customer_key,
                        now,
                    )
                )
                if registration_session is None:
                    session.rollback()
                    raise BillingRegistrationExpiredOrUsedError
                registration_session_id = int(registration_session.id)
                session.commit()
                return registration_session_id
            except BillingServiceError:
                session.rollback()
                raise
            except Exception:
                session.rollback()
                raise BillingPersistenceError from None

    def _mark_registration_failed(self, registration_session_id: int) -> None:
        with get_session() as session:
            try:
                changed = self.repository.fail_registration_session(
                    session,
                    registration_session_id,
                    datetime.now(timezone.utc),
                )
                if changed:
                    session.commit()
                else:
                    session.rollback()
            except Exception:
                session.rollback()

    def _raise_after_compensation(
        self,
        billing_key: str,
        registration_session_id: int,
        error_type: type[BillingServiceError],
    ) -> NoReturn:
        try:
            self.billing_client.delete_billing_key(billing_key)
            compensated = True
        except Exception:
            compensated = False
        self._mark_registration_failed(registration_session_id)
        if not compensated:
            raise BillingCompensationError from None
        raise error_type from None

    def _cleanup_old_billing_keys(
        self,
        billing_methods: list[tuple[int, str]],
    ) -> bool:
        cleanup_required = False
        for _, encrypted_billing_key in billing_methods:
            try:
                billing_key = self.billing_key_cipher.decrypt(
                    encrypted_billing_key
                )
                self.billing_client.delete_billing_key(billing_key)
            except Exception:
                cleanup_required = True
        return cleanup_required

    @staticmethod
    def _lock_active_user(session, user_id: int) -> User | None:
        return session.scalar(
            select(User)
            .where(User.id == user_id, User.status == "ACTIVE")
            .with_for_update()
        )
