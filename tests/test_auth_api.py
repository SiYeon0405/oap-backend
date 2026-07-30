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
                },
            )

        self.assertEqual(response.status_code, 201)
        self.assertNotIn("token", response.text.lower())

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
        response = self.client.post(
            "/api/v1/auth/logout",
            headers={"Origin": "https://attacker.example"},
        )
        self.assertEqual(response.status_code, 403)
