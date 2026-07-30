import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import bcrypt
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.refresh_token_session import RefreshTokenSession
from app.models.user import User
from app.schemas.auth import LoginRequest
from app.services.auth_service import AuthService, InvalidCredentialsError


class AuthRefreshSessionTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        event.listen(
            self.engine,
            "connect",
            lambda connection, _: connection.create_function(
                "now",
                0,
                lambda: datetime.now(timezone.utc).isoformat(" "),
            ),
        )
        Base.metadata.create_all(
            self.engine,
            tables=[User.__table__, RefreshTokenSession.__table__],
        )
        self.session_factory = sessionmaker(bind=self.engine)
        self.environment = patch.dict(
            os.environ,
            {
                "JWT_SECRET": "test-only-secret",
                "JWT_ACCESS_EXPIRE_MINUTES": "30",
                "JWT_REFRESH_EXPIRE_DAYS": "14",
            },
            clear=True,
        )
        self.session_patch = patch(
            "app.services.auth_service.get_session",
            side_effect=self.session_factory,
        )
        self.environment.start()
        self.session_patch.start()
        with self.session_factory() as session:
            session.add(
                User(
                    email="user@example.com",
                    password_hash=bcrypt.hashpw(
                        b"password123",
                        bcrypt.gensalt(),
                    ).decode("utf-8"),
                    name="User",
                    status="ACTIVE",
                )
            )
            session.commit()

    def tearDown(self):
        self.session_patch.stop()
        self.environment.stop()
        self.engine.dispose()

    def _login(self):
        return AuthService().login(
            LoginRequest(email="user@example.com", password="password123")
        )

    def test_login_stores_only_refresh_token_hash(self):
        result = self._login()

        with self.session_factory() as session:
            stored = session.scalar(select(RefreshTokenSession))
            self.assertIsNotNone(stored)
            self.assertNotEqual(stored.token_hash, result.refresh_token)
            self.assertEqual(
                stored.token_hash,
                AuthService._hash_refresh_token(result.refresh_token),
            )

    def test_refresh_rotates_session_and_detects_reuse(self):
        first = self._login()
        second = AuthService().refresh(first.refresh_token)

        with self.session_factory() as session:
            rows = session.scalars(
                select(RefreshTokenSession).order_by(RefreshTokenSession.id)
            ).all()
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0].revoke_reason, "rotated")
            self.assertEqual(rows[0].replaced_by_jti, rows[1].jti)
            self.assertEqual(rows[0].token_family, rows[1].token_family)
            self.assertNotEqual(rows[0].jti, rows[1].jti)

        with self.assertRaises(InvalidCredentialsError):
            AuthService().refresh(first.refresh_token)

        with self.session_factory() as session:
            active = session.scalars(
                select(RefreshTokenSession).where(
                    RefreshTokenSession.revoked_at.is_(None)
                )
            ).all()
            self.assertEqual(active, [])

        with self.assertRaises(InvalidCredentialsError):
            AuthService().refresh(second.refresh_token)

    def test_logout_revokes_only_current_device_family(self):
        first_device = self._login()
        second_device = self._login()

        AuthService().logout(first_device.refresh_token)

        with self.assertRaises(InvalidCredentialsError):
            AuthService().refresh(first_device.refresh_token)
        refreshed_second_device = AuthService().refresh(
            second_device.refresh_token
        )
        self.assertTrue(refreshed_second_device.refresh_token)

    def test_access_token_cannot_be_used_as_refresh_token(self):
        access_token = AuthService()._create_token(
            1,
            token_type="access",
            expires_delta=timedelta(minutes=30),
        )

        with self.assertRaises(InvalidCredentialsError):
            AuthService().refresh(access_token)

    def test_expired_refresh_token_is_rejected(self):
        refresh_token = AuthService()._create_token(
            1,
            token_type="refresh",
            expires_delta=timedelta(seconds=-1),
            token_family="expired-family",
        )

        with self.assertRaises(InvalidCredentialsError):
            AuthService().refresh(refresh_token)

    def test_inactive_user_refresh_is_rejected(self):
        result = self._login()
        with self.session_factory() as session:
            user = session.scalar(select(User))
            user.status = "INACTIVE"
            session.commit()

        with self.assertRaises(InvalidCredentialsError):
            AuthService().refresh(result.refresh_token)
