import os
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.services.auth_service import LoginResult


class AuthApiTest(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(
            os.environ,
            {
                "JWT_SECRET": "test-only-secret",
                "COOKIE_SECURE": "false",
                "COOKIE_SAMESITE": "lax",
            },
            clear=True,
        )
        self.environment.start()
        self.client = TestClient(app)
        self.user = SimpleNamespace(
            id=42,
            email="user@example.com",
            name="User",
            status="ACTIVE",
            created_at=datetime.now(timezone.utc),
        )

    def tearDown(self):
        self.client.close()
        self.environment.stop()

    def test_signup_without_tokens_succeeds_and_returns_no_token(self):
        with patch("app.api.auth.AuthService.signup", return_value=self.user):
            response = self.client.post(
                "/api/v1/auth/signup",
                json={
                    "email": "user@example.com",
                    "password": "password123",
                    "name": "User",
                    "termsAgreed": True,
                    "privacyAgreed": True,
                    "marketingAgreed": False,
                },
            )

        self.assertEqual(response.status_code, 201)
        self.assertNotIn("token", response.text.lower())
        self.assertEqual(
            set(response.json()),
            {"id", "email", "name", "status", "createdAt"},
        )

    def test_signup_rejects_missing_required_consent(self):
        for field in ("termsAgreed", "privacyAgreed"):
            payload = {
                "email": "user@example.com",
                "password": "password123",
                "name": "User",
                "termsAgreed": True,
                "privacyAgreed": True,
                "marketingAgreed": False,
            }
            payload[field] = False
            with self.subTest(field=field), patch(
                "app.api.auth.AuthService.signup"
            ) as signup:
                response = self.client.post("/api/v1/auth/signup", json=payload)
                self.assertEqual(response.status_code, 422)
                signup.assert_not_called()

    def test_signup_requires_nonblank_name_and_defaults_marketing(self):
        base_payload = {
            "email": "user@example.com",
            "password": "password123",
            "termsAgreed": True,
            "privacyAgreed": True,
        }
        for name in (None, "", "   "):
            payload = {**base_payload, "name": name}
            with self.subTest(name=name), patch(
                "app.api.auth.AuthService.signup"
            ) as signup:
                response = self.client.post("/api/v1/auth/signup", json=payload)
                self.assertEqual(response.status_code, 422)
                signup.assert_not_called()

        with patch("app.api.auth.AuthService.signup") as signup:
            response = self.client.post(
                "/api/v1/auth/signup", json=base_payload
            )
            self.assertEqual(response.status_code, 422)
            signup.assert_not_called()

        with patch(
            "app.api.auth.AuthService.signup", return_value=self.user
        ) as signup:
            response = self.client.post(
                "/api/v1/auth/signup",
                json={**base_payload, "name": "  User  "},
            )
        self.assertEqual(response.status_code, 201)
        request = signup.call_args.args[0]
        self.assertEqual(request.name, "User")
        self.assertFalse(request.marketingAgreed)

    def test_unauthenticated_consent_read_is_401(self):
        response = self.client.get("/api/v1/auth/consents")
        self.assertEqual(response.status_code, 401)

    def test_consent_response_does_not_expose_request_metadata(self):
        from app.api.auth import get_current_user

        app.dependency_overrides[get_current_user] = lambda: self.user
        consent_response = {
            "current": [
                {
                    "type": "MARKETING",
                    "documentVersion": "2.1",
                    "agreed": False,
                    "occurredAt": datetime.now(timezone.utc),
                }
            ],
            "history": [],
        }
        try:
            with patch(
                "app.api.auth.UserConsentService.get_consents",
                return_value=consent_response,
            ):
                response = self.client.get("/api/v1/auth/consents")
        finally:
            app.dependency_overrides.clear()
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("ip", response.text.lower())
        self.assertNotIn("useragent", response.text.lower())
        self.assertNotIn("token", response.text.lower())

    def test_marketing_change_uses_current_user_and_origin_validation(self):
        from app.api.auth import get_current_user

        app.dependency_overrides[get_current_user] = lambda: self.user
        current = {
            "type": "MARKETING",
            "documentVersion": "2.1",
            "agreed": False,
            "occurredAt": datetime.now(timezone.utc),
        }
        try:
            with patch(
                "app.api.auth.UserConsentService.set_marketing",
                return_value=current,
            ) as set_marketing:
                response = self.client.patch(
                    "/api/v1/auth/consents/marketing",
                    json={"agreed": False},
                    headers={
                        "Origin": "http://localhost:3000",
                        "X-Forwarded-For": "203.0.113.10",
                    },
                )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(set_marketing.call_args.args, (42, False))
            self.assertNotEqual(
                set_marketing.call_args.kwargs["ip_address"],
                "203.0.113.10",
            )

            rejected = self.client.patch(
                "/api/v1/auth/consents/marketing",
                json={"agreed": True},
                headers={"Origin": "https://attacker.example"},
            )
            self.assertEqual(rejected.status_code, 403)
            self.assertEqual(
                self.client.patch(
                    "/api/v1/auth/consents/terms", json={"agreed": False}
                ).status_code,
                404,
            )
        finally:
            app.dependency_overrides.clear()

    def test_login_sets_httponly_cookies_without_token_json(self):
        result = LoginResult(
            user=self.user,
            access_token="access-value",
            refresh_token="refresh-value",
        )
        with patch("app.api.auth.AuthService.login", return_value=result):
            response = self.client.post(
                "/api/v1/auth/login",
                json={"email": "user@example.com", "password": "password123"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("token", response.text.lower())
        cookies = response.headers.get_list("set-cookie")
        self.assertTrue(
            any(
                "access_token=" in value
                and "HttpOnly" in value
                and "Path=/" in value
                and "SameSite=lax" in value
                and "Max-Age=1800" in value
                for value in cookies
            )
        )
        self.assertTrue(
            any(
                "refresh_token=" in value
                and "HttpOnly" in value
                and "Path=/api/v1/auth" in value
                and "SameSite=lax" in value
                and "Max-Age=1209600" in value
                for value in cookies
            )
        )

    def test_refresh_without_cookie_returns_401(self):
        response = self.client.post("/api/v1/auth/refresh")
        self.assertEqual(response.status_code, 401)

    def test_configured_origin_allows_refresh_and_logout(self):
        result = LoginResult(
            user=self.user,
            access_token="new-access-value",
            refresh_token="new-refresh-value",
        )
        origin = {"Origin": "https://frontend.example/"}
        with patch.dict(
            os.environ,
            {"CORS_ALLOWED_ORIGINS": "https://frontend.example"},
        ), patch("app.api.auth.AuthService.refresh", return_value=result) as refresh:
            response = self.client.post(
                "/api/v1/auth/refresh",
                headers={**origin, "Cookie": "refresh_token=refresh-value"},
            )
            self.assertEqual(response.status_code, 200)
            refresh.assert_called_once_with("refresh-value")

            with patch("app.api.auth.AuthService.logout") as logout:
                response = self.client.post(
                    "/api/v1/auth/logout",
                    headers=origin,
                )
            self.assertEqual(response.status_code, 200)
            logout.assert_called_once()

    def test_logout_is_idempotent_and_clears_both_cookies(self):
        with patch("app.api.auth.AuthService.logout") as logout:
            response = self.client.post("/api/v1/auth/logout")

        self.assertEqual(response.status_code, 200)
        logout.assert_called_once_with(None)
        cookies = response.headers.get_list("set-cookie")
        self.assertTrue(
            any(
                "access_token=" in value
                and "Max-Age=0" in value
                and "Path=/" in value
                for value in cookies
            )
        )
        self.assertTrue(
            any(
                "refresh_token=" in value
                and "Max-Age=0" in value
                and "Path=/api/v1/auth" in value
                for value in cookies
            )
        )

    def test_account_delete_requires_authentication(self):
        response = self.client.request(
            "DELETE",
            "/api/v1/auth/me",
            json={"password": "password123"},
        )
        self.assertEqual(response.status_code, 401)

    def test_sensitive_routes_reject_untrusted_origin(self):
        for path in ("/api/v1/auth/refresh", "/api/v1/auth/logout"):
            with self.subTest(path=path):
                response = self.client.post(
                    path,
                    headers={"Origin": "https://attacker.example"},
                )
                self.assertEqual(response.status_code, 403)
