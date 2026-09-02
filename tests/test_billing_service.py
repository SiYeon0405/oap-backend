import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from app.repositories.billing_repository import BillingRepository
from app.services.billing_security import (
    BillingKeyCipher,
    BillingKeyDecryptionError,
    BillingKeyEncryptionError,
)
from app.services.billing_service import (
    BillingCompensationError,
    BillingPersistenceError,
    BillingProviderError,
    BillingRegistrationExpiredOrUsedError,
    BillingService,
    BillingUserUnavailableError,
)
from app.services.toss_billing_client import (
    TossBillingClient,
    TossBillingKeyIssueResult,
    TossBillingTransportError,
)


TEST_USER_ID = 11
TEST_REGISTRATION_ID = 22
TEST_BILLING_METHOD_ID = 33
TEST_AUTH_VALUE = "TEST_AUTH_VALUE"
TEST_CUSTOMER_VALUE = "TEST_CUSTOMER_VALUE"
TEST_BILLING_VALUE = "TEST_BILLING_VALUE"
TEST_ENCRYPTED_VALUE = "TEST_ENCRYPTED_VALUE"
TEST_AUTHENTICATED_AT = "TEST_AUTHENTICATED_AT"


class SessionContext:
    def __init__(self, session):
        self.session = session

    def __enter__(self):
        return self.session

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class BillingServiceTest(unittest.TestCase):
    def setUp(self):
        self.repository = MagicMock(spec=BillingRepository)
        self.client = MagicMock(spec=TossBillingClient)
        self.cipher = MagicMock(spec=BillingKeyCipher)
        self.service = BillingService(
            repository=self.repository,
            billing_client=self.client,
            billing_key_cipher=self.cipher,
        )

    @staticmethod
    def session(active_user=True):
        session = MagicMock()
        session.scalar.return_value = object() if active_user else None
        return session

    @staticmethod
    def issued_result():
        return TossBillingKeyIssueResult(
            billing_key=TEST_BILLING_VALUE,
            customer_key=TEST_CUSTOMER_VALUE,
            authenticated_at=TEST_AUTHENTICATED_AT,
            method="TEST_METHOD",
            card_issuer_code="TEST_ISSUER",
            card_number_masked="MASKED_TEST_VALUE",
        )

    @staticmethod
    def sessions(*sessions):
        return patch(
            "app.services.billing_service.get_session",
            side_effect=[SessionContext(session) for session in sessions],
        )

    def prepare_completion(self, old_methods=None):
        self.repository.claim_pending_registration_session.return_value = (
            SimpleNamespace(id=TEST_REGISTRATION_ID)
        )
        self.repository.list_active_billing_methods_by_user_id.return_value = (
            old_methods or []
        )
        self.repository.complete_registration_session.return_value = True
        self.repository.fail_registration_session.return_value = True
        self.client.issue_billing_key.return_value = self.issued_result()
        self.cipher.encrypt.return_value = TEST_ENCRYPTED_VALUE

        def assign_id(_session, billing_method):
            billing_method.id = TEST_BILLING_METHOD_ID
            return billing_method

        self.repository.add_billing_method.side_effect = assign_id

    def complete(self, *sessions):
        with self.sessions(*sessions):
            return self.service.complete_registration(
                TEST_USER_ID,
                TEST_CUSTOMER_VALUE,
                TEST_AUTH_VALUE,
            )

    def test_start_registration_creates_pending_session(self):
        session = self.session()
        before = datetime.now(timezone.utc)
        with self.sessions(session):
            result = self.service.start_registration(TEST_USER_ID)
        after = datetime.now(timezone.utc)

        registration = self.repository.add_registration_session.call_args.args[1]
        UUID(registration.customer_key)
        self.assertEqual(registration.user_id, TEST_USER_ID)
        self.assertEqual(registration.status, "PENDING")
        self.assertEqual(result.customer_key, registration.customer_key)
        self.assertIsNotNone(result.expires_at.tzinfo)
        self.assertGreaterEqual(result.expires_at, before + timedelta(minutes=15))
        self.assertLessEqual(result.expires_at, after + timedelta(minutes=15))
        self.assertNotIn(result.customer_key, repr(result))
        self.repository.expire_pending_registration_sessions_by_user_id.assert_called_once()
        session.commit.assert_called_once_with()
        self.client.issue_billing_key.assert_not_called()

    def test_start_registration_rejects_unavailable_user(self):
        session = self.session(active_user=False)
        with self.sessions(session), self.assertRaises(BillingUserUnavailableError):
            self.service.start_registration(TEST_USER_ID)
        self.repository.add_registration_session.assert_not_called()
        session.commit.assert_not_called()
        self.client.issue_billing_key.assert_not_called()

    def test_complete_registration_rejects_expired_or_used_session(self):
        claim_session = self.session()
        self.repository.claim_pending_registration_session.return_value = None
        with self.sessions(claim_session), self.assertRaises(
            BillingRegistrationExpiredOrUsedError
        ):
            self.service.complete_registration(
                TEST_USER_ID,
                TEST_CUSTOMER_VALUE,
                TEST_AUTH_VALUE,
            )
        self.client.issue_billing_key.assert_not_called()
        self.cipher.encrypt.assert_not_called()
        self.repository.add_billing_method.assert_not_called()

    def test_complete_registration_marks_failed_when_provider_fails(self):
        self.prepare_completion()
        claim_session = self.session()
        failed_session = self.session()
        self.client.issue_billing_key.side_effect = TossBillingTransportError(
            "TEST_PROVIDER_FAILURE"
        )
        with self.assertRaises(BillingProviderError):
            self.complete(claim_session, failed_session)
        claim_session.commit.assert_called_once_with()
        self.repository.fail_registration_session.assert_called_once()
        failed_session.commit.assert_called_once_with()
        self.client.delete_billing_key.assert_not_called()
        self.repository.add_billing_method.assert_not_called()

    def test_complete_registration_saves_encrypted_billing_method(self):
        self.prepare_completion()
        claim_session = self.session()
        save_session = self.session()
        result = self.complete(claim_session, save_session)

        self.client.issue_billing_key.assert_called_once_with(
            TEST_AUTH_VALUE,
            TEST_CUSTOMER_VALUE,
        )
        self.cipher.encrypt.assert_called_once_with(TEST_BILLING_VALUE)
        billing_method = self.repository.add_billing_method.call_args.args[1]
        self.assertEqual(billing_method.billing_key_encrypted, TEST_ENCRYPTED_VALUE)
        self.assertNotIn(TEST_BILLING_VALUE, vars(billing_method).values())
        self.repository.deactivate_billing_methods_by_user_id.assert_called_once()
        save_session.flush.assert_called_once_with()
        self.repository.complete_registration_session.assert_called_once()
        save_session.commit.assert_called_once_with()
        self.assertEqual(result.billing_method_id, TEST_BILLING_METHOD_ID)
        self.assertEqual(result.card_issuer_code, "TEST_ISSUER")
        self.assertEqual(result.card_number_masked, "MASKED_TEST_VALUE")
        self.assertEqual(result.authenticated_at, TEST_AUTHENTICATED_AT)
        self.assertFalse(result.cleanup_required)
        for sensitive in (
            TEST_AUTH_VALUE,
            TEST_CUSTOMER_VALUE,
            TEST_BILLING_VALUE,
            TEST_ENCRYPTED_VALUE,
        ):
            self.assertNotIn(sensitive, repr(result))
        self.client.delete_billing_key.assert_not_called()

    def test_complete_registration_deletes_new_key_when_encryption_fails(self):
        self.prepare_completion()
        claim_session = self.session()
        failed_session = self.session()
        self.cipher.encrypt.side_effect = BillingKeyEncryptionError(
            "TEST_ENCRYPTION_FAILURE"
        )
        with self.assertRaises(BillingPersistenceError):
            self.complete(claim_session, failed_session)
        self.client.delete_billing_key.assert_called_once_with(TEST_BILLING_VALUE)
        self.repository.fail_registration_session.assert_called_once()
        failed_session.commit.assert_called_once_with()
        self.repository.add_billing_method.assert_not_called()

    def test_complete_registration_raises_compensation_error_when_cleanup_fails(self):
        self.prepare_completion()
        claim_session = self.session()
        failed_session = self.session()
        self.cipher.encrypt.side_effect = BillingKeyEncryptionError(
            "TEST_ENCRYPTION_FAILURE"
        )
        self.client.delete_billing_key.side_effect = TossBillingTransportError(
            "TEST_DELETE_FAILURE"
        )
        with self.assertRaises(BillingCompensationError) as caught:
            self.complete(claim_session, failed_session)
        self.repository.fail_registration_session.assert_called_once()
        for sensitive in (
            TEST_AUTH_VALUE,
            TEST_CUSTOMER_VALUE,
            TEST_BILLING_VALUE,
            TEST_ENCRYPTED_VALUE,
            "TEST_DELETE_FAILURE",
        ):
            self.assertNotIn(sensitive, str(caught.exception))
            self.assertNotIn(sensitive, repr(caught.exception))

    def test_complete_registration_compensates_when_database_save_fails(self):
        self.prepare_completion()
        claim_session = self.session()
        save_session = self.session()
        failed_session = self.session()
        self.repository.add_billing_method.side_effect = SQLAlchemyError(
            "TEST_DATABASE_FAILURE"
        )
        with self.assertRaises(BillingPersistenceError):
            self.complete(claim_session, save_session, failed_session)
        save_session.commit.assert_not_called()
        save_session.rollback.assert_called()
        self.client.delete_billing_key.assert_called_once_with(TEST_BILLING_VALUE)
        self.repository.fail_registration_session.assert_called_once()
        failed_session.commit.assert_called_once_with()

    def test_complete_registration_reports_compensation_failure(self):
        self.prepare_completion()
        claim_session = self.session()
        save_session = self.session()
        failed_session = self.session()
        self.repository.add_billing_method.side_effect = SQLAlchemyError(
            "TEST_DATABASE_FAILURE"
        )
        self.client.delete_billing_key.side_effect = TossBillingTransportError(
            "TEST_DELETE_FAILURE"
        )
        with self.assertRaises(BillingCompensationError):
            self.complete(claim_session, save_session, failed_session)
        self.repository.fail_registration_session.assert_called_once()

    def test_complete_registration_deletes_previous_billing_keys_after_commit(self):
        events = []
        old_methods = [
            SimpleNamespace(id=1, billing_key_encrypted="TEST_OLD_ENCRYPTED_1"),
            SimpleNamespace(id=2, billing_key_encrypted="TEST_OLD_ENCRYPTED_2"),
        ]
        self.prepare_completion(old_methods)
        claim_session = self.session()
        save_session = self.session()
        self.repository.claim_pending_registration_session.side_effect = lambda *args: (
            events.append("claim") or SimpleNamespace(id=TEST_REGISTRATION_ID)
        )
        claim_session.commit.side_effect = lambda: events.append("processing commit")
        self.client.issue_billing_key.side_effect = lambda *args: (
            events.append("issue") or self.issued_result()
        )
        self.cipher.encrypt.side_effect = lambda value: (
            events.append("encrypt") or TEST_ENCRYPTED_VALUE
        )
        save_session.commit.side_effect = lambda: events.append("database commit")
        self.cipher.decrypt.side_effect = lambda value: (
            events.append("old decrypt") or value.replace("ENCRYPTED", "KEY")
        )
        self.client.delete_billing_key.side_effect = lambda value: events.append(
            "old delete"
        )

        result = self.complete(claim_session, save_session)

        self.assertFalse(result.cleanup_required)
        self.assertEqual(self.cipher.decrypt.call_count, 2)
        self.assertEqual(
            self.client.delete_billing_key.call_args_list,
            [call("TEST_OLD_KEY_1"), call("TEST_OLD_KEY_2")],
        )
        self.assertLess(events.index("claim"), events.index("processing commit"))
        self.assertLess(events.index("processing commit"), events.index("issue"))
        self.assertLess(events.index("issue"), events.index("encrypt"))
        self.assertLess(events.index("database commit"), events.index("old delete"))

    def test_complete_registration_returns_cleanup_required_when_old_key_cleanup_fails(self):
        old_methods = [
            SimpleNamespace(id=1, billing_key_encrypted="TEST_OLD_ENCRYPTED_1"),
            SimpleNamespace(id=2, billing_key_encrypted="TEST_OLD_ENCRYPTED_2"),
        ]
        self.prepare_completion(old_methods)
        claim_session = self.session()
        save_session = self.session()
        self.cipher.decrypt.side_effect = [
            BillingKeyDecryptionError("TEST_OLD_DECRYPT_FAILURE"),
            "TEST_OLD_KEY_2",
        ]

        result = self.complete(claim_session, save_session)

        self.assertTrue(result.cleanup_required)
        save_session.commit.assert_called_once_with()
        save_session.rollback.assert_not_called()
        self.client.delete_billing_key.assert_called_once_with("TEST_OLD_KEY_2")
        self.assertNotIn(TEST_ENCRYPTED_VALUE, repr(result))

    def test_complete_registration_compensates_when_session_completion_loses_state(self):
        self.prepare_completion()
        claim_session = self.session()
        save_session = self.session()
        failed_session = self.session()
        self.repository.complete_registration_session.return_value = False
        with self.assertRaises(BillingPersistenceError):
            self.complete(claim_session, save_session, failed_session)
        save_session.flush.assert_called_once_with()
        save_session.commit.assert_not_called()
        save_session.rollback.assert_called()
        self.client.delete_billing_key.assert_called_once_with(TEST_BILLING_VALUE)
        self.repository.fail_registration_session.assert_called_once()

    def test_service_does_not_close_injected_client(self):
        self.service.close()
        self.client.close.assert_not_called()


if __name__ == "__main__":
    unittest.main()
