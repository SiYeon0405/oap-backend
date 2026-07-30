import os
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import jwt

from app.schemas.auth import LoginRequest
from app.services.auth_service import AuthService


class FakeSession:
    def __init__(self, user):
        self.user = user

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def scalar(self, statement):
        return self.user

    def add(self, value):
        self.added = value

    def commit(self):
        pass

    def rollback(self):
        pass

    def refresh(self, value):
        pass


class AuthServiceJwtDefaultsTest(unittest.TestCase):
    def setUp(self):
        self.service = AuthService()

    def test_jwt_secret_remains_required(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(
                RuntimeError,
                "JWT_SECRET is not configured",
            ):
                self.service._create_token(
                    1,
                    token_type="access",
                    expires_delta=timedelta(minutes=30),
                )

    def test_issuer_and_audience_use_defaults_when_missing_or_blank(self):
        for optional_environment in (
            {},
            {"JWT_ISSUER": "", "JWT_AUDIENCE": ""},
        ):
            with self.subTest(optional_environment=optional_environment):
                environment = {
                    "JWT_SECRET": "test-only-secret",
                    **optional_environment,
                }
                with patch.dict(os.environ, environment, clear=True):
                    token = self.service._create_token(
                        1,
                        token_type="access",
                        expires_delta=timedelta(minutes=30),
                    )

                payload = jwt.decode(
                    token,
                    options={
                        "verify_signature": False,
                        "verify_exp": False,
                        "verify_aud": False,
                    },
                )
                self.assertEqual(payload["iss"], "oap-backend")
                self.assertEqual(payload["aud"], "oap-web")

    def test_explicit_issuer_and_audience_take_precedence(self):
        environment = {
            "JWT_SECRET": "test-only-secret",
            "JWT_ISSUER": "custom-issuer",
            "JWT_AUDIENCE": "custom-audience",
        }
        with patch.dict(os.environ, environment, clear=True):
            token = self.service._create_token(
                1,
                token_type="access",
                expires_delta=timedelta(minutes=30),
            )

        payload = jwt.decode(
            token,
            options={
                "verify_signature": False,
                "verify_exp": False,
                "verify_aud": False,
            },
        )
        self.assertEqual(payload["iss"], "custom-issuer")
        self.assertEqual(payload["aud"], "custom-audience")

    def test_login_uses_default_expiration_values_when_missing_or_blank(self):
        for optional_environment in (
            {},
            {
                "JWT_ACCESS_EXPIRE_MINUTES": "",
                "JWT_REFRESH_EXPIRE_DAYS": "",
            },
        ):
            with self.subTest(optional_environment=optional_environment):
                user = SimpleNamespace(
                    id=1,
                    email="user@example.com",
                    password_hash="stored-hash",
                    status="ACTIVE",
                )
                with (
                    patch.dict(os.environ, optional_environment, clear=True),
                    patch(
                        "app.services.auth_service.get_session",
                        return_value=FakeSession(user),
                    ),
                    patch(
                        "app.services.auth_service.bcrypt.checkpw",
                        return_value=True,
                    ),
                    patch.object(
                        self.service,
                        "_create_token",
                        side_effect=["access-token", "refresh-token"],
                    ) as create_token,
                ):
                    self.service.login(
                        LoginRequest(
                            email="user@example.com",
                            password="password",
                        )
                    )

                self.assertEqual(
                    create_token.call_args_list[0].kwargs["expires_delta"],
                    timedelta(minutes=30),
                )
                self.assertEqual(
                    create_token.call_args_list[1].kwargs["expires_delta"],
                    timedelta(days=14),
                )

    def test_login_prefers_explicit_expiration_values(self):
        user = SimpleNamespace(
            id=1,
            email="user@example.com",
            password_hash="stored-hash",
            status="ACTIVE",
        )
        environment = {
            "JWT_ACCESS_EXPIRE_MINUTES": "45",
            "JWT_REFRESH_EXPIRE_DAYS": "21",
        }
        with (
            patch.dict(os.environ, environment, clear=True),
            patch(
                "app.services.auth_service.get_session",
                return_value=FakeSession(user),
            ),
            patch(
                "app.services.auth_service.bcrypt.checkpw",
                return_value=True,
            ),
            patch.object(
                self.service,
                "_create_token",
                side_effect=["access-token", "refresh-token"],
            ) as create_token,
        ):
            self.service.login(
                LoginRequest(
                    email="user@example.com",
                    password="password",
                )
            )

        self.assertEqual(
            create_token.call_args_list[0].kwargs["expires_delta"],
            timedelta(minutes=45),
        )
        self.assertEqual(
            create_token.call_args_list[1].kwargs["expires_delta"],
            timedelta(days=21),
        )
