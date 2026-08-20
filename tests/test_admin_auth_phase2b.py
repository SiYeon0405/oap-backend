import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import UUID

import bcrypt
import jwt
import pyotp
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.admin_auth import AdminApiError, require_admin_permission
from app.core.config import Settings
from app.main import app
from app.models.admin import (
    AdminAuditLog,
    AdminMfaChallenge,
    AdminRefreshTokenSession,
    AdminUser,
)
from app.services.admin_auth_service import AdminAuthService
from app.services.admin_security import (
    create_admin_access_token,
    encrypt_mfa_secret,
)


class AdminAuthPhase2BTest(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(
            _env_file=None,
            app_env="test",
            database_url="sqlite://",
            admin_jwt_secret="phase-2b-admin-test-secret",
            admin_jwt_issuer="oap-admin-phase-2b",
            admin_jwt_audience="oap-admin-web-phase-2b",
            admin_mfa_encryption_key=Fernet.generate_key().decode("ascii"),
            admin_allowed_origins="https://admin.test",
            admin_cookie_secure=False,
        )
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        event.listen(
            self.engine,
            "connect",
            lambda connection, _: connection.create_function(
                "now", 0, lambda: datetime.now(timezone.utc).isoformat()
            ),
        )
        for table in (
            AdminUser.__table__,
            AdminMfaChallenge.__table__,
            AdminRefreshTokenSession.__table__,
            AdminAuditLog.__table__,
        ):
            table.create(self.engine, checkfirst=True)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.patchers = [
            patch(
                "app.services.admin_auth_service.get_session",
                side_effect=self.sessions,
            ),
            patch(
                "app.services.admin_auth_service.get_settings",
                return_value=self.settings,
            ),
            patch("app.api.admin_auth.get_settings", return_value=self.settings),
            patch(
                "app.services.admin_security.get_settings",
                return_value=self.settings,
            ),
            patch(
                "app.api.admin_auth.get_admin_allowed_origins",
                return_value=["https://admin.test"],
            ),
        ]
        for patcher in self.patchers:
            patcher.start()
        self.client = TestClient(app)
        self.initial_csrf = "bff-initial-csrf"
        self.client.cookies.set(
            "admin_csrf_token",
            self.initial_csrf,
            domain="testserver.local",
            path="/api/v1/admin",
        )
        self.headers = {
            "Origin": "https://admin.test",
            "X-Admin-CSRF-Token": self.initial_csrf,
        }
        self.secret = pyotp.random_base32()
        self.admin_id = self._create_admin()

    def tearDown(self):
        self.client.close()
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.engine.dispose()

    def _create_admin(self, **overrides):
        values = {
            "email": "admin@example.com",
            "password_hash": bcrypt.hashpw(
                b"password123", bcrypt.gensalt()
            ).decode(),
            "name": "Test Admin",
            "role": "analyst",
            "is_active": True,
            "mfa_secret_encrypted": encrypt_mfa_secret(
                self.secret, self.settings
            ),
        }
        values.update(overrides)
        with self.sessions() as session:
            admin = AdminUser(**values)
            session.add(admin)
            session.commit()
            return admin.id

    def _login(self, email=" ADMIN@example.com ", password="password123"):
        return self.client.post(
            "/api/v1/admin/auth/login",
            json={"email": email, "password": password},
            headers=self.headers,
        )

    def _authenticate(self):
        login = self._login()
        challenge_id = login.json()["challengeId"]
        response = self.client.post(
            "/api/v1/admin/auth/mfa/verify",
            json={
                "challengeId": challenge_id,
                "code": pyotp.TOTP(self.secret).now(),
            },
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        return response

    def _current_csrf_headers(self):
        return {
            "Origin": "https://admin.test",
            "X-Admin-CSRF-Token": self.client.cookies.get(
                "admin_csrf_token"
            ),
        }

    def test_login_normalizes_email_creates_challenge_without_auth_cookies(self):
        response = self._login()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["mfaRequired"], True)
        self.assertEqual(response.json()["expiresInSeconds"], 300)
        cookies = response.headers.get_list("set-cookie")
        self.assertFalse(any("admin_access_token" in value for value in cookies))
        self.assertFalse(any("admin_refresh_token" in value for value in cookies))
        with self.sessions() as session:
            challenge = session.scalar(select(AdminMfaChallenge))
            self.assertEqual(challenge.admin_id, self.admin_id)
            self.assertEqual(
                session.scalar(
                    select(func.count(AdminAuditLog.id)).where(
                        AdminAuditLog.action.in_(
                            ("admin_login_succeeded", "admin_mfa_succeeded")
                        )
                    )
                ),
                0,
            )

    def test_unknown_email_and_wrong_password_have_same_response(self):
        unknown = self._login("missing@example.com", "wrong-password")
        wrong = self._login(password="wrong-password")
        self.assertEqual(unknown.status_code, 401)
        self.assertEqual(unknown.json()["error"]["code"], wrong.json()["error"]["code"])
        self.assertNotIn("missing@example.com", unknown.text)
        with self.sessions() as session:
            logs = session.scalars(select(AdminAuditLog)).all()
            self.assertTrue(all(log.target_id != "missing@example.com" for log in logs))

    def test_five_password_failures_lock_account_without_details(self):
        for _ in range(5):
            response = self._login(password="wrong-password")
            self.assertEqual(response.status_code, 401)
        with self.sessions() as session:
            admin = session.get(AdminUser, self.admin_id)
            self.assertEqual(admin.failed_login_count, 5)
            self.assertGreater(
                admin.locked_until.replace(tzinfo=timezone.utc),
                datetime.now(timezone.utc),
            )
        blocked = self._login()
        self.assertEqual(blocked.status_code, 401)
        self.assertNotIn("15", blocked.text)
        self.assertNotIn("attempt", blocked.text.lower())

    def test_origin_and_csrf_are_required_and_exact(self):
        cases = (
            {},
            {"Origin": "https://admin.test.evil", "X-Admin-CSRF-Token": self.initial_csrf},
            {"Origin": "https://admin.test", "X-Admin-CSRF-Token": "wrong"},
        )
        for headers in cases:
            with self.subTest(headers=headers):
                response = self.client.post(
                    "/api/v1/admin/auth/login",
                    json={"email": "admin@example.com", "password": "password123"},
                    headers=headers,
                )
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.headers["cache-control"], "private, no-store")

    def test_mfa_success_sets_separate_cookies_and_me_is_minimal(self):
        response = self._authenticate()
        self.assertEqual(response.json(), {"authenticated": True})
        cookies = response.headers.get_list("set-cookie")
        self.assertTrue(any("admin_access_token=" in value and "HttpOnly" in value and "Path=/api/v1/admin" in value for value in cookies))
        self.assertTrue(any("admin_refresh_token=" in value and "HttpOnly" in value and "Path=/api/v1/admin/auth" in value for value in cookies))
        self.assertTrue(any("admin_csrf_token=" in value and "HttpOnly" not in value for value in cookies))
        me = self.client.get("/api/v1/admin/auth/me")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(
            set(me.json()), {"id", "email", "name", "role", "permissions"}
        )
        self.assertEqual(
            me.json()["permissions"],
            ["dashboard:read", "errors:read", "events:read"],
        )
        with self.sessions() as session:
            success_logs = session.scalars(
                select(AdminAuditLog).where(
                    AdminAuditLog.action.in_(
                        ("admin_mfa_succeeded", "admin_login_succeeded")
                    )
                )
            ).all()
            self.assertEqual(len(success_logs), 2)
            self.assertEqual(
                {log.action for log in success_logs},
                {"admin_mfa_succeeded", "admin_login_succeeded"},
            )
            self.assertEqual({log.admin_id for log in success_logs}, {self.admin_id})
            self.assertEqual(len({log.request_id for log in success_logs}), 1)
            self.assertEqual(
                session.scalar(select(func.count(AdminRefreshTokenSession.id))),
                1,
            )

    def test_mfa_failure_limit_expiry_reuse_and_inactive_admin(self):
        login = self._login()
        challenge_id = login.json()["challengeId"]
        for _ in range(5):
            response = self.client.post(
                "/api/v1/admin/auth/mfa/verify",
                json={"challengeId": challenge_id, "code": "000000"},
                headers=self.headers,
            )
            self.assertEqual(response.status_code, 401)
        with self.sessions() as session:
            challenge = session.get(AdminMfaChallenge, UUID(challenge_id))
            self.assertEqual(challenge.failed_attempts, 5)
            actions = session.scalars(select(AdminAuditLog.action)).all()
            self.assertNotIn("admin_login_succeeded", actions)
            self.assertNotIn("admin_mfa_succeeded", actions)
            self.assertIn("admin_mfa_failed", actions)

        for mode in ("expired", "consumed", "inactive"):
            with self.sessions() as session:
                challenge = AdminMfaChallenge(
                    admin_id=self.admin_id,
                    expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
                )
                if mode == "expired":
                    challenge.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
                if mode == "consumed":
                    challenge.consumed_at = datetime.now(timezone.utc)
                if mode == "inactive":
                    session.get(AdminUser, self.admin_id).is_active = False
                session.add(challenge)
                session.commit()
                challenge_id = str(challenge.id)
            response = self.client.post(
                "/api/v1/admin/auth/mfa/verify",
                json={"challengeId": challenge_id, "code": pyotp.TOTP(self.secret).now()},
                headers=self.headers,
            )
            self.assertEqual(response.status_code, 401)
            self.assertFalse(
                any(
                    "admin_access_token" in value
                    or "admin_refresh_token" in value
                    for value in response.headers.get_list("set-cookie")
                )
            )
            if mode == "expired":
                with self.sessions() as session:
                    self.assertEqual(
                        session.scalar(
                            select(func.count(AdminAuditLog.id)).where(
                                AdminAuditLog.action == "admin_login_succeeded"
                            )
                        ),
                        0,
                    )
            if mode == "inactive":
                with self.sessions() as session:
                    session.get(AdminUser, self.admin_id).is_active = True
                    session.commit()

    def test_refresh_rotates_tokens_and_reuse_revokes_family(self):
        self._authenticate()
        old_refresh = self.client.cookies.get("admin_refresh_token")
        old_csrf = self.client.cookies.get("admin_csrf_token")
        response = self.client.post(
            "/api/v1/admin/auth/refresh",
            headers=self._current_csrf_headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"refreshed": True})
        self.assertNotEqual(self.client.cookies.get("admin_refresh_token"), old_refresh)
        self.assertNotEqual(self.client.cookies.get("admin_csrf_token"), old_csrf)
        with self.sessions() as session:
            rows = session.scalars(
                select(AdminRefreshTokenSession).order_by(AdminRefreshTokenSession.id)
            ).all()
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0].revoke_reason, "rotated")
            self.assertEqual(rows[0].token_family, rows[1].token_family)

        self.client.cookies.set(
            "admin_refresh_token",
            old_refresh,
            domain="testserver.local",
            path="/api/v1/admin/auth",
        )
        self.client.cookies.set(
            "admin_csrf_token",
            old_csrf,
            domain="testserver.local",
            path="/api/v1/admin",
        )
        self.client.cookies.delete(
            "admin_access_token",
            domain="testserver.local",
            path="/api/v1/admin",
        )
        reused = self.client.post(
            "/api/v1/admin/auth/refresh",
            headers={
                "Origin": "https://admin.test",
                "X-Admin-CSRF-Token": old_csrf,
            },
        )
        self.assertEqual(reused.status_code, 401)
        with self.sessions() as session:
            admin = session.get(AdminUser, self.admin_id)
            active = session.scalars(
                select(AdminRefreshTokenSession).where(
                    AdminRefreshTokenSession.revoked_at.is_(None)
                )
            ).all()
            self.assertEqual(active, [])
            self.assertEqual(admin.session_version, 2)

    def test_logout_is_idempotent_revokes_all_and_invalidates_access(self):
        self._authenticate()
        old_access = self.client.cookies.get("admin_access_token")
        response = self.client.post(
            "/api/v1/admin/auth/logout", headers=self._current_csrf_headers()
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"loggedOut": True})
        self.client.cookies.set(
            "admin_access_token",
            old_access,
            domain="testserver.local",
            path="/api/v1/admin",
        )
        self.assertEqual(self.client.get("/api/v1/admin/auth/me").status_code, 401)
        with self.sessions() as session:
            self.assertEqual(session.get(AdminUser, self.admin_id).session_version, 2)
            self.assertEqual(
                session.scalar(
                    select(AdminRefreshTokenSession.revoke_reason)
                ),
                "logout",
            )

        self.client.cookies.set(
            "admin_csrf_token",
            "new-initial",
            domain="testserver.local",
            path="/api/v1/admin",
        )
        self.client.cookies.delete(
            "admin_access_token",
            domain="testserver.local",
            path="/api/v1/admin",
        )
        second = self.client.post(
            "/api/v1/admin/auth/logout",
            headers={
                "Origin": "https://admin.test",
                "X-Admin-CSRF-Token": "new-initial",
            },
        )
        self.assertEqual(second.status_code, 200)

    def test_access_rejects_user_cookie_inactive_and_session_version(self):
        self.client.cookies.set(
            "access_token",
            "regular-user-cookie",
            domain="testserver.local",
            path="/",
        )
        self.assertEqual(self.client.get("/api/v1/admin/auth/me").status_code, 401)
        self.client.cookies.set(
            "admin_access_token",
            "not-an-admin-token",
            domain="testserver.local",
            path="/api/v1/admin",
        )
        self.assertEqual(self.client.get("/api/v1/admin/auth/me").status_code, 401)
        self.client.cookies.delete(
            "admin_access_token",
            domain="testserver.local",
            path="/api/v1/admin",
        )
        self._authenticate()
        with self.sessions() as session:
            admin = session.get(AdminUser, self.admin_id)
            admin.is_active = False
            session.commit()
        self.assertEqual(self.client.get("/api/v1/admin/auth/me").status_code, 401)
        with self.sessions() as session:
            admin = session.get(AdminUser, self.admin_id)
            admin.is_active = True
            admin.session_version += 1
            session.commit()
        self.assertEqual(self.client.get("/api/v1/admin/auth/me").status_code, 401)

        wrong_audience = self.settings.model_copy(
            update={"admin_jwt_audience": "wrong-audience"}
        )
        token = create_admin_access_token(
            self.admin_id, 2, "csrf", wrong_audience
        )
        self.client.cookies.set(
            "admin_access_token",
            token,
            domain="testserver.local",
            path="/api/v1/admin",
        )
        self.assertEqual(self.client.get("/api/v1/admin/auth/me").status_code, 401)

        now = datetime.now(timezone.utc)
        expired = jwt.encode(
            {
                "sub": f"admin:{self.admin_id}",
                "iat": now - timedelta(minutes=20),
                "exp": now - timedelta(minutes=10),
                "iss": self.settings.admin_jwt_issuer,
                "aud": self.settings.admin_jwt_audience,
                "token_type": "admin_access",
                "jti": "expired-jti",
                "csrf": "csrf",
                "session_version": 2,
            },
            self.settings.admin_jwt_secret,
            algorithm="HS256",
        )
        self.client.cookies.set(
            "admin_access_token",
            expired,
            domain="testserver.local",
            path="/api/v1/admin",
        )
        self.assertEqual(self.client.get("/api/v1/admin/auth/me").status_code, 401)

    def test_permission_factory_and_response_contract(self):
        admin = AdminUser(role="analyst")
        self.assertIs(require_admin_permission("events:read")(admin), admin)
        with self.assertRaises(AdminApiError) as raised:
            require_admin_permission("users:read")(admin)
        self.assertEqual(raised.exception.status_code, 403)

        invalid = self.client.post(
            "/api/v1/admin/auth/mfa/verify",
            json={"challengeId": "not-a-uuid", "code": 123456},
            headers=self.headers,
        )
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(set(invalid.json()), {"error"})
        self.assertEqual(invalid.headers["cache-control"], "private, no-store")

    def test_audit_logs_are_masked_and_contain_no_credentials(self):
        self._login(password="wrong-password")
        with self.sessions() as session:
            log = session.scalar(select(AdminAuditLog))
            self.assertNotEqual(log.ip_address_masked, "127.0.0.1")
            serialized = f"{log.target_id}{log.audit_metadata}"
            self.assertNotIn("admin@example.com", serialized)
            self.assertNotIn("wrong-password", serialized)

    def test_service_failure_never_sets_auth_cookies(self):
        login = self._login()
        original_audit = AdminAuthService._audit

        def fail_login_success_audit(
            session, admin_id, action, target_id, request_id, ip_address, result
        ):
            if action == "admin_login_succeeded":
                raise RuntimeError("audit unavailable")
            return original_audit(
                session,
                admin_id,
                action,
                target_id,
                request_id,
                ip_address,
                result,
            )

        with patch.object(
            AdminAuthService,
            "_audit",
            side_effect=fail_login_success_audit,
        ):
            response = self.client.post(
                "/api/v1/admin/auth/mfa/verify",
                json={
                    "challengeId": login.json()["challengeId"],
                    "code": pyotp.TOTP(self.secret).now(),
                },
                headers=self.headers,
            )
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("audit unavailable", response.text)
        self.assertFalse(any("admin_access_token" in value for value in response.headers.get_list("set-cookie")))
        with self.sessions() as session:
            challenge = session.get(
                AdminMfaChallenge, UUID(login.json()["challengeId"])
            )
            self.assertIsNone(challenge.consumed_at)
            self.assertEqual(
                session.scalar(select(func.count(AdminRefreshTokenSession.id))),
                0,
            )
            self.assertEqual(
                session.scalar(
                    select(func.count(AdminAuditLog.id)).where(
                        AdminAuditLog.action.in_(
                            ("admin_mfa_succeeded", "admin_login_succeeded")
                        )
                    )
                ),
                0,
            )


if __name__ == "__main__":
    unittest.main()
