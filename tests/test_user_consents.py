import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.user import User
from app.models.user_consent import UserConsent
from app.schemas.auth import SignupRequest
from app.services.auth_service import AuthService
from app.services.user_consent_service import (
    CURRENT_CONSENT_DOCUMENT_VERSION,
    UserConsentService,
)


class UserConsentIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        event.listen(
            self.engine,
            "connect",
            self._configure_sqlite,
        )
        Base.metadata.create_all(
            self.engine,
            tables=[User.__table__, UserConsent.__table__],
        )
        self.session_factory = sessionmaker(bind=self.engine)
        self.auth_session_patch = patch(
            "app.services.auth_service.get_session",
            side_effect=self.session_factory,
        )
        self.consent_session_patch = patch(
            "app.services.user_consent_service.get_session",
            side_effect=self.session_factory,
        )
        self.auth_session_patch.start()
        self.consent_session_patch.start()

    def tearDown(self):
        self.consent_session_patch.stop()
        self.auth_session_patch.stop()
        self.engine.dispose()

    @staticmethod
    def _configure_sqlite(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.create_function(
            "now", 0, lambda: datetime.now(timezone.utc).isoformat(" ")
        )

    @staticmethod
    def signup_request(marketing=False):
        return SignupRequest(
            email="user@example.com",
            password="password123",
            name="User",
            termsAgreed=True,
            privacyAgreed=True,
            marketingAgreed=marketing,
        )

    def signup(self, marketing=False):
        return AuthService().signup(
            self.signup_request(marketing),
            ip_address="127.0.0.1",
            user_agent="test-agent",
        )

    def test_signup_stores_all_server_controlled_consents(self):
        before = datetime.now(timezone.utc)
        user = self.signup(marketing=False)
        after = datetime.now(timezone.utc)

        with self.session_factory() as session:
            rows = session.scalars(
                select(UserConsent).order_by(UserConsent.consent_type)
            ).all()
        self.assertEqual(user.email, "user@example.com")
        self.assertEqual(
            {row.consent_type: row.is_agreed for row in rows},
            {"MARKETING": False, "PRIVACY": True, "TERMS": True},
        )
        self.assertEqual(
            {row.document_version for row in rows},
            {CURRENT_CONSENT_DOCUMENT_VERSION},
        )
        self.assertTrue(all(before <= row.occurred_at.replace(tzinfo=timezone.utc) <= after for row in rows))
        self.assertEqual({row.ip_address for row in rows}, {"127.0.0.1"})
        self.assertEqual({row.user_agent for row in rows}, {"test-agent"})

    def test_signup_rolls_back_user_when_consent_save_fails(self):
        with patch(
            "app.services.auth_service.UserConsentService.add_initial_consents",
            side_effect=RuntimeError("consent failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "consent failed"):
                self.signup()
        with self.session_factory() as session:
            self.assertEqual(session.scalar(select(func.count(User.id))), 0)

    def test_current_history_marketing_append_and_idempotency(self):
        user = self.signup(marketing=False)
        service = UserConsentService()

        initial = service.get_consents(user.id)
        self.assertEqual(len(initial.current), 3)
        self.assertEqual(len(initial.history), 3)

        withdrawn = service.set_marketing(
            user.id,
            False,
            ip_address=None,
            user_agent=None,
        )
        self.assertFalse(withdrawn.agreed)
        with self.session_factory() as session:
            self.assertEqual(session.scalar(select(func.count(UserConsent.id))), 3)

        agreed = service.set_marketing(
            user.id,
            True,
            ip_address="127.0.0.1",
            user_agent="agent",
        )
        self.assertTrue(agreed.agreed)
        withdrawn = service.set_marketing(
            user.id,
            False,
            ip_address="127.0.0.1",
            user_agent="agent",
        )
        self.assertFalse(withdrawn.agreed)

        result = service.get_consents(user.id)
        marketing = [item for item in result.history if item.type == "MARKETING"]
        self.assertEqual([item.agreed for item in marketing], [False, True, False])
        current = {item.type: item for item in result.current}
        self.assertFalse(current["MARKETING"].agreed)
        self.assertEqual(len(result.history), 5)

    def test_deleting_user_cascades_consent_history(self):
        user = self.signup()
        with self.session_factory() as session:
            stored = session.get(User, user.id)
            session.delete(stored)
            session.commit()
            self.assertEqual(session.scalar(select(func.count(UserConsent.id))), 0)


if __name__ == "__main__":
    unittest.main()
