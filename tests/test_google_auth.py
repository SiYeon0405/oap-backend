import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import bcrypt
import jwt
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import get_current_user
from app.main import app
from app.models.base import Base
from app.models.marketing_consent import MarketingConsent
from app.models.refresh_token_session import RefreshTokenSession
from app.models.user import User
from app.models.user_consent import UserConsent
from app.schemas.auth import DeleteAccountRequest, GoogleLoginRequest
from app.services.auth_service import (
    AccountDeletionConfigurationError,
    AccountDeletionError,
    AuthService,
    GoogleEmailConflictError,
    LoginResult,
)
from app.services.google_identity_service import (
    GoogleAudienceMismatchError,
    GoogleEmailNotVerifiedError,
    GoogleIdentity,
    GoogleIdentityConfigurationError,
    GoogleIdentityService,
    GoogleTokenExpiredError,
    GoogleTokenVerificationError,
    InvalidGoogleProfileError,
)


class GoogleIdentityServiceTest(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(
            os.environ,
            {"GOOGLE_CLIENT_ID": "google-client-id"},
            clear=True,
        )
        self.environment.start()

    def tearDown(self):
        self.environment.stop()

    @staticmethod
    def token(**overrides):
        claims = {
            "sub": "google-subject",
            "email": "user@example.com",
            "name": "Google User",
            "email_verified": True,
            "aud": "google-client-id",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        }
        claims.update(overrides)
        return jwt.encode(claims, "untrusted-test-key", algorithm="HS256")

    def test_verified_token_returns_normalized_identity(self):
        claims = {
            "sub": " google-subject ",
            "email": "USER@EXAMPLE.COM",
            "name": " Google User ",
            "email_verified": True,
            "aud": "google-client-id",
        }
        with patch(
            "app.services.google_identity_service.id_token.verify_oauth2_token",
            return_value=claims,
        ) as verify:
            identity = GoogleIdentityService().verify(self.token())
        self.assertEqual(identity.sub, "google-subject")
        self.assertEqual(identity.email, "user@example.com")
        self.assertEqual(identity.name, "Google User")
        self.assertEqual(verify.call_args.args[2], "google-client-id")

    def test_rejects_verification_failure(self):
        with patch(
            "app.services.google_identity_service.id_token.verify_oauth2_token",
            side_effect=ValueError("signature or issuer rejected"),
        ):
            with self.assertRaises(GoogleTokenVerificationError):
                GoogleIdentityService().verify(self.token())

    def test_missing_client_id_is_configuration_error(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(GoogleIdentityConfigurationError):
                GoogleIdentityService().verify(self.token())

    def test_recent_verification_rejects_stale_issued_at(self):
        verified_claims = {
            "sub": "google-subject",
            "email": "user@example.com",
            "name": "Google User",
            "email_verified": True,
            "aud": "google-client-id",
        }
        with patch(
            "app.services.google_identity_service.id_token.verify_oauth2_token",
            return_value=verified_claims,
        ):
            identity = GoogleIdentityService().verify_recent(self.token())
            self.assertEqual(identity.sub, "google-subject")

            with self.assertRaises(GoogleTokenVerificationError):
                GoogleIdentityService().verify_recent(
                    self.token(
                        iat=datetime.now(timezone.utc) - timedelta(minutes=6)
                    )
                )

    def test_rejects_audience_mismatch_before_google_request(self):
        with patch(
            "app.services.google_identity_service.id_token.verify_oauth2_token"
        ) as verify:
            with self.assertRaises(GoogleAudienceMismatchError):
                GoogleIdentityService().verify(self.token(aud="other-client"))
        verify.assert_not_called()

    def test_rejects_expired_token_before_google_request(self):
        with patch(
            "app.services.google_identity_service.id_token.verify_oauth2_token"
        ) as verify:
            with self.assertRaises(GoogleTokenExpiredError):
                GoogleIdentityService().verify(
                    self.token(exp=datetime.now(timezone.utc) - timedelta(seconds=1))
                )
        verify.assert_not_called()

    def test_rejects_unverified_email_and_blank_name(self):
        for claims, error in (
            (
                {
                    "sub": "subject",
                    "email": "user@example.com",
                    "name": "User",
                    "email_verified": False,
                    "aud": "google-client-id",
                },
                GoogleEmailNotVerifiedError,
            ),
            (
                {
                    "sub": "subject",
                    "email": "user@example.com",
                    "name": "   ",
                    "email_verified": True,
                    "aud": "google-client-id",
                },
                InvalidGoogleProfileError,
            ),
        ):
            with self.subTest(error=error), patch(
                "app.services.google_identity_service.id_token.verify_oauth2_token",
                return_value=claims,
            ):
                with self.assertRaises(error):
                    GoogleIdentityService().verify(self.token())


class GoogleAuthIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        def configure_connection(connection, _):
            connection.create_function(
                "now", 0, lambda: datetime.now(timezone.utc).isoformat(" ")
            )
            connection.execute("PRAGMA foreign_keys=ON")

        event.listen(self.engine, "connect", configure_connection)
        Base.metadata.create_all(
            self.engine,
            tables=[
                User.__table__,
                UserConsent.__table__,
                MarketingConsent.__table__,
                RefreshTokenSession.__table__,
            ],
        )
        self.session_factory = sessionmaker(bind=self.engine)
        self.environment = patch.dict(
            os.environ,
            {"JWT_SECRET": "test-only-secret"},
            clear=True,
        )
        self.session_patch = patch(
            "app.services.auth_service.get_session",
            side_effect=self.session_factory,
        )
        self.environment.start()
        self.session_patch.start()
        self.identity_service = MagicMock()
        self.identity_service.verify.return_value = GoogleIdentity(
            sub="google-subject",
            email="google@example.com",
            name="Google User",
        )

    def tearDown(self):
        self.session_patch.stop()
        self.environment.stop()
        self.engine.dispose()

    @staticmethod
    def request():
        return GoogleLoginRequest(
            idToken="google-id-token",
            termsAgreed=True,
            privacyAgreed=True,
            marketingAgreed=False,
        )

    def login(self):
        return AuthService().google_login(
            self.request(), identity_service=self.identity_service
        )

    def test_new_and_repeated_google_login_reuses_user_and_creates_sessions(self):
        first = self.login()
        second = self.login()
        self.assertEqual(first.user.id, second.user.id)
        with self.session_factory() as session:
            self.assertEqual(session.scalar(select(func.count(User.id))), 1)
            self.assertEqual(
                session.scalar(select(func.count(RefreshTokenSession.id))), 2
            )
            self.assertEqual(
                session.scalar(select(func.count(UserConsent.id))), 2
            )
            self.assertEqual(
                session.scalar(select(func.count(MarketingConsent.id))), 1
            )
            stored = session.scalar(select(User))
            self.assertNotIn("google-id-token", str(stored.__dict__))

    def test_google_signup_stores_marketing_opt_in(self):
        request = self.request().model_copy(update={"marketingAgreed": True})
        AuthService().google_login(
            request,
            identity_service=self.identity_service,
        )
        with self.session_factory() as session:
            self.assertTrue(
                session.scalar(select(MarketingConsent)).is_agreed
            )

    def test_local_email_collision_is_not_automatically_linked(self):
        with self.session_factory() as session:
            session.add(
                User(
                    email="google@example.com",
                    password_hash="local-password-hash",
                    name="Local User",
                    status="ACTIVE",
                )
            )
            session.commit()
        with self.assertRaises(GoogleEmailConflictError):
            self.login()

    def test_google_signup_rolls_back_on_consent_failure(self):
        with patch(
            "app.services.auth_service.UserConsentService.add_initial_consents",
            side_effect=RuntimeError("consent failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "consent failed"):
                self.login()
        with self.session_factory() as session:
            self.assertEqual(session.scalar(select(func.count(User.id))), 0)
            self.assertEqual(
                session.scalar(select(func.count(RefreshTokenSession.id))), 0
            )

    def test_local_account_deletion_requires_matching_password(self):
        with self.session_factory() as session:
            user = User(
                email="local@example.com",
                password_hash=bcrypt.hashpw(
                    b"correct-password", bcrypt.gensalt()
                ).decode("utf-8"),
                name="Local User",
                status="ACTIVE",
            )
            session.add(user)
            session.commit()
            user_id = user.id

        service = AuthService()
        for request in (
            DeleteAccountRequest(password="wrong-password"),
            DeleteAccountRequest(idToken="google-id-token"),
            DeleteAccountRequest(
                password="correct-password",
                idToken="google-id-token",
            ),
            DeleteAccountRequest(),
        ):
            with self.subTest(request=request), self.assertRaises(
                AccountDeletionError
            ):
                service.delete_account(user_id, request)

        with self.session_factory() as session:
            self.assertIsNotNone(session.get(User, user_id))

        service.delete_account(
            user_id,
            DeleteAccountRequest(password="correct-password"),
        )
        with self.session_factory() as session:
            self.assertIsNone(session.get(User, user_id))

    def test_google_account_deletion_requires_recent_matching_google_sub(self):
        result = self.login()
        user_id = result.user.id
        service = AuthService()
        with self.session_factory() as session:
            other_user = User(
                email="other@example.com",
                password_hash="other-user-password-hash",
                name="Other User",
                status="ACTIVE",
            )
            session.add(other_user)
            session.commit()
            other_user_id = other_user.id

        self.identity_service.verify_recent.return_value = GoogleIdentity(
            sub="different-subject",
            email="google@example.com",
            name="Google User",
        )
        with self.assertRaises(AccountDeletionError):
            service.delete_account(
                user_id,
                DeleteAccountRequest(idToken="other-sub-token"),
                identity_service=self.identity_service,
            )

        for error in (
            GoogleTokenExpiredError(),
            GoogleAudienceMismatchError(),
            GoogleTokenVerificationError(),
        ):
            self.identity_service.verify_recent.side_effect = error
            with self.subTest(error=type(error).__name__), self.assertRaises(
                AccountDeletionError
            ):
                service.delete_account(
                    user_id,
                    DeleteAccountRequest(idToken="invalid-google-token"),
                    identity_service=self.identity_service,
                )

        self.identity_service.verify_recent.side_effect = None
        with self.assertRaises(AccountDeletionError):
            service.delete_account(
                user_id,
                DeleteAccountRequest(password="unused-password"),
                identity_service=self.identity_service,
            )

        with self.session_factory() as session:
            self.assertIsNotNone(session.get(User, user_id))
            self.assertEqual(
                session.scalar(select(func.count(RefreshTokenSession.id))), 1
            )

        self.identity_service.verify_recent.return_value = GoogleIdentity(
            sub="google-subject",
            email="google@example.com",
            name="Google User",
        )
        service.delete_account(
            user_id,
            DeleteAccountRequest(idToken="valid-google-token"),
            identity_service=self.identity_service,
        )
        with self.session_factory() as session:
            self.assertIsNone(session.get(User, user_id))
            self.assertIsNotNone(session.get(User, other_user_id))
            self.assertEqual(session.scalar(select(func.count(User.id))), 1)
            self.assertEqual(
                session.scalar(select(func.count(RefreshTokenSession.id))), 0
            )
            self.assertEqual(
                session.scalar(select(func.count(UserConsent.id))), 0
            )
            self.assertEqual(
                session.scalar(select(func.count(MarketingConsent.id))), 0
            )

    def test_google_account_deletion_reports_missing_configuration(self):
        result = self.login()
        self.identity_service.verify_recent.side_effect = GoogleIdentityConfigurationError(
            "GOOGLE_CLIENT_ID is not configured"
        )
        with self.assertRaises(AccountDeletionConfigurationError):
            AuthService().delete_account(
                result.user.id,
                DeleteAccountRequest(idToken="google-id-token"),
                identity_service=self.identity_service,
            )
        with self.session_factory() as session:
            self.assertIsNotNone(session.get(User, result.user.id))


class GoogleAuthApiTest(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(
            os.environ,
            {
                "CORS_ALLOWED_ORIGINS": (
                    "http://localhost:3000,http://localhost:3001,"
                    "http://localhost:5173,https://www.ooap.co.kr"
                )
            },
        )
        self.environment.start()
        self.client = TestClient(app)
        self.user = SimpleNamespace(
            id=51,
            email="google@example.com",
            name="Google User",
            google_sub="google-subject",
            status="ACTIVE",
        )
        app.dependency_overrides[get_current_user] = lambda: self.user

    def tearDown(self):
        app.dependency_overrides.clear()
        self.client.close()
        self.environment.stop()

    def test_google_login_sets_existing_auth_cookies_without_token_json(self):
        result = LoginResult(
            user=self.user,
            access_token="access-value",
            refresh_token="refresh-value",
        )
        with patch(
            "app.api.auth.AuthService.google_login", return_value=result
        ):
            response = self.client.post(
                "/api/v1/auth/google",
                headers={"Origin": "https://www.ooap.co.kr"},
                json={
                    "idToken": "google-id-token",
                    "termsAgreed": True,
                    "privacyAgreed": True,
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("token", response.text.lower())
        cookies = response.headers.get_list("set-cookie")
        self.assertTrue(
            any(
                "access_token=" in value
                and "HttpOnly" in value
                and "Path=/" in value
                for value in cookies
            )
        )
        self.assertTrue(
            any(
                "refresh_token=" in value
                and "HttpOnly" in value
                and "Path=/api/v1/auth" in value
                for value in cookies
            )
        )

    def test_google_login_missing_configuration_is_503(self):
        with patch(
            "app.api.auth.AuthService.google_login",
            side_effect=GoogleIdentityConfigurationError(
                "GOOGLE_CLIENT_ID is not configured"
            ),
        ):
            response = self.client.post(
                "/api/v1/auth/google",
                headers={"Origin": "https://www.ooap.co.kr"},
                json={
                    "idToken": "google-id-token",
                    "termsAgreed": True,
                    "privacyAgreed": True,
                },
            )
        self.assertEqual(response.status_code, 503)

    def test_google_login_rejects_untrusted_origin_and_maps_errors(self):
        response = self.client.post(
            "/api/v1/auth/google",
            headers={"Origin": "https://attacker.example"},
            json={
                "idToken": "google-id-token",
                "termsAgreed": True,
                "privacyAgreed": True,
            },
        )
        self.assertEqual(response.status_code, 403)

        cases = (
            (GoogleTokenVerificationError(), 401),
            (GoogleAudienceMismatchError(), 401),
            (GoogleTokenExpiredError(), 401),
            (GoogleEmailNotVerifiedError(), 401),
            (InvalidGoogleProfileError(), 422),
            (GoogleEmailConflictError(), 409),
        )
        for error, expected in cases:
            with self.subTest(error=type(error).__name__), patch(
                "app.api.auth.AuthService.google_login", side_effect=error
            ):
                response = self.client.post(
                    "/api/v1/auth/google",
                    headers={"Origin": "https://www.ooap.co.kr"},
                    json={
                        "idToken": "google-id-token",
                        "termsAgreed": True,
                        "privacyAgreed": True,
                    },
                )
                self.assertEqual(response.status_code, expected)
                self.assertNotIn("google-id-token", response.text)

    def test_google_account_delete_clears_cookies_only_after_success(self):
        origin = {"Origin": "https://www.ooap.co.kr"}
        with patch("app.api.auth.AuthService.delete_account") as delete_account:
            response = self.client.request(
                "DELETE",
                "/api/v1/auth/me",
                headers=origin,
                json={"idToken": "google-id-token"},
            )
        self.assertEqual(response.status_code, 200)
        delete_account.assert_called_once()
        cookies = response.headers.get_list("set-cookie")
        self.assertTrue(any("access_token=" in value for value in cookies))
        self.assertTrue(any("refresh_token=" in value for value in cookies))

        for error, expected in (
            (AccountDeletionError(), 401),
            (AccountDeletionConfigurationError(), 503),
        ):
            with self.subTest(error=type(error).__name__), patch(
                "app.api.auth.AuthService.delete_account", side_effect=error
            ):
                response = self.client.request(
                    "DELETE",
                    "/api/v1/auth/me",
                    headers=origin,
                    json={"idToken": "google-id-token"},
                )
                self.assertEqual(response.status_code, expected)
                self.assertEqual(response.headers.get_list("set-cookie"), [])


if __name__ == "__main__":
    unittest.main()
