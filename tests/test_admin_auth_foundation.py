import os
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import jwt
import pyotp
from cryptography.fernet import Fernet

from app.core.admin_permissions import (
    InvalidAdminRoleError,
    permissions_for_role,
)
from app.core.config import Settings, get_admin_allowed_origins
from app.models.admin import (
    AdminAuditLog,
    AdminMfaChallenge,
    AdminRefreshTokenSession,
    AdminUser,
)
from app.services.admin_security import (
    AdminMfaSecretError,
    AdminSecurityConfigurationError,
    AdminTokenError,
    InvalidAuditMetadataError,
    build_totp_uri,
    create_admin_access_token,
    create_admin_refresh_token,
    decode_admin_token,
    decrypt_mfa_secret,
    encrypt_mfa_secret,
    generate_totp_secret,
    increment_session_version,
    mask_ip_address,
    session_version_matches,
    validate_audit_metadata,
    verify_totp_code,
)
from app.services.auth_service import AuthService, InvalidCredentialsError


class AdminAuthFoundationTest(unittest.TestCase):
    def settings(self, **overrides):
        values = {
            "app_env": "test",
            "database_url": "sqlite://",
            "admin_jwt_secret": "phase-2a-admin-test-secret",
            "admin_jwt_issuer": "oap-admin-test",
            "admin_jwt_audience": "oap-admin-web-test",
            "admin_mfa_encryption_key": Fernet.generate_key().decode("ascii"),
        }
        values.update(overrides)
        return Settings(_env_file=None, **values)

    def test_models_have_required_constraints_foreign_keys_and_indexes(self):
        self.assertEqual(
            {table.__tablename__ for table in (
                AdminUser,
                AdminMfaChallenge,
                AdminRefreshTokenSession,
                AdminAuditLog,
            )},
            {
                "admin_users",
                "admin_mfa_challenges",
                "admin_refresh_token_sessions",
                "admin_audit_logs",
            },
        )
        self.assertTrue(AdminUser.__table__.c.email.unique)
        self.assertTrue(AdminRefreshTokenSession.__table__.c.jti.unique)
        checks = {
            constraint.name
            for table in (AdminUser, AdminMfaChallenge, AdminAuditLog)
            for constraint in table.__table__.constraints
            if constraint.name
        }
        self.assertTrue(
            {
                "ck_admin_users_role",
                "ck_admin_users_session_version",
                "ck_admin_users_failed_login_count",
                "ck_admin_mfa_challenges_failed_attempts",
                "ck_admin_audit_logs_result",
            }.issubset(checks)
        )
        foreign_keys = {
            table.__tablename__: next(iter(table.__table__.foreign_keys)).ondelete
            for table in (AdminMfaChallenge, AdminRefreshTokenSession, AdminAuditLog)
        }
        self.assertEqual(
            foreign_keys,
            {
                "admin_mfa_challenges": "CASCADE",
                "admin_refresh_token_sessions": "CASCADE",
                "admin_audit_logs": "SET NULL",
            },
        )
        indexes = {
            index.name
            for table in (AdminMfaChallenge, AdminRefreshTokenSession, AdminAuditLog)
            for index in table.__table__.indexes
        }
        self.assertEqual(len(indexes), 10)
        self.assertIsNotNone(AdminAuditLog.__table__.c.metadata.server_default)

    def test_admin_config_is_separate_and_fail_closed(self):
        defaults = Settings(_env_file=None, app_env="test", database_url="sqlite://")
        self.assertIsNone(defaults.admin_jwt_secret)
        self.assertEqual(defaults.admin_access_token_expire_minutes, 10)
        self.assertEqual(defaults.admin_refresh_token_expire_days, 14)
        self.assertIsNone(defaults.admin_cookie_domain)
        self.assertEqual(get_admin_allowed_origins(defaults), ["https://admin.ooap.co.kr"])
        with self.assertRaises(AdminSecurityConfigurationError):
            create_admin_access_token(1, 1, "csrf", defaults)

        with patch.dict(os.environ, {"JWT_SECRET": "user-only-secret"}, clear=True):
            isolated = Settings(_env_file=None, app_env="test", database_url="sqlite://")
        self.assertIsNone(isolated.admin_jwt_secret)

    def test_mfa_encryption_round_trip_and_failures_are_generalized(self):
        settings = self.settings()
        secret = generate_totp_secret()
        ciphertext = encrypt_mfa_secret(secret, settings)
        self.assertNotEqual(ciphertext, secret)
        self.assertEqual(decrypt_mfa_secret(ciphertext, settings), secret)

        failures = (
            (ciphertext, self.settings()),
            (ciphertext[:-2] + "xx", settings),
        )
        for damaged, selected_settings in failures:
            with self.subTest(damaged=damaged[-4:]):
                with self.assertRaises(AdminMfaSecretError) as raised:
                    decrypt_mfa_secret(damaged, selected_settings)
                self.assertNotIn(secret, str(raised.exception))
                self.assertNotIn(settings.admin_mfa_encryption_key, str(raised.exception))

    def test_totp_generation_uri_and_verification(self):
        secret = generate_totp_secret()
        code = pyotp.TOTP(secret).now()
        self.assertTrue(build_totp_uri(secret, "admin@example.test", "OAP Admin").startswith("otpauth://totp/"))
        self.assertTrue(verify_totp_code(secret, code))
        self.assertFalse(verify_totp_code(secret, "000000") if code != "000000" else verify_totp_code(secret, "111111"))

    def test_admin_jwt_namespaces_and_claims_are_separate(self):
        settings = self.settings()
        access = create_admin_access_token(7, 3, "csrf-value", settings)
        refresh = create_admin_refresh_token(7, "family-id", "csrf-value", settings)
        access_payload = decode_admin_token(access, "admin_access", settings)
        refresh_payload = decode_admin_token(refresh, "admin_refresh", settings)
        self.assertEqual(access_payload["sub"], "admin:7")
        self.assertEqual(access_payload["session_version"], 3)
        self.assertEqual(refresh_payload["token_family"], "family-id")
        self.assertTrue(session_version_matches(access_payload, 3))
        self.assertFalse(session_version_matches(access_payload, 4))
        with self.assertRaises(AdminTokenError):
            decode_admin_token(access, "admin_refresh", settings)

        with patch.dict(
            os.environ,
            {
                "JWT_SECRET": "user-test-secret",
                "JWT_ISSUER": "oap-user-test",
                "JWT_AUDIENCE": "oap-user-web-test",
            },
            clear=True,
        ):
            user_token = AuthService()._create_token(9, "access", timedelta(minutes=5))
            with self.assertRaises(InvalidCredentialsError):
                AuthService()._decode_token(access, "access")
        with self.assertRaises(AdminTokenError):
            decode_admin_token(user_token, "admin_access", settings)

    def test_session_version_increment_basis(self):
        admin = SimpleNamespace(session_version=1)
        self.assertEqual(increment_session_version(admin), 2)
        self.assertEqual(admin.session_version, 2)

    def test_permissions_are_fixed_by_role(self):
        self.assertEqual(
            permissions_for_role("analyst"),
            frozenset({"dashboard:read", "events:read", "errors:read"}),
        )
        self.assertIn("users:read", permissions_for_role("support"))
        self.assertIn("admins:manage", permissions_for_role("super_admin"))
        with self.assertRaises(InvalidAdminRoleError):
            permissions_for_role("unknown")

    def test_ip_masking_and_audit_metadata_allowlist(self):
        self.assertEqual(mask_ip_address("192.0.2.129"), "192.0.2.0")
        self.assertEqual(mask_ip_address("2001:db8:1234:5678::1"), "2001:db8:1234:5678::")
        self.assertIsNone(mask_ip_address("not-an-ip"))
        self.assertEqual(validate_audit_metadata({"role": "analyst"}), {"role": "analyst"})
        for metadata in ({"password": "x"}, {"mfaCode": "123456"}, {"unknown": "x"}):
            with self.subTest(metadata=metadata):
                with self.assertRaises(InvalidAuditMetadataError):
                    validate_audit_metadata(metadata)

    def test_migration_is_single_additive_revision(self):
        path = "alembic/versions/20260820_add_admin_auth_foundation.py"
        source = Path(path).read_text(encoding="utf-8")
        self.assertIn('revision = "20260820_admin_auth"', source)
        self.assertIn('down_revision = "20260820_analytics_events"', source)
        self.assertEqual(source.count("op.create_table("), 4)
        self.assertNotIn("op.add_column", source)
        self.assertNotIn("CREATE EXTENSION", source)


if __name__ == "__main__":
    unittest.main()
