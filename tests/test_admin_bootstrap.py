import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from unittest.mock import patch

import bcrypt
import pyotp
from cryptography.fernet import Fernet
from pydantic import ValidationError
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.services.admin_bootstrap_service as bootstrap_module
from app.cli.create_admin import main
from app.core.config import Settings
from app.models.admin import AdminAuditLog, AdminUser
from app.services.admin_bootstrap_service import (
    AdminAlreadyExistsError,
    AdminBootstrapError,
    AdminBootstrapResult,
    AdminBootstrapService,
)
from app.services.admin_security import (
    AdminSecurityConfigurationError,
    decrypt_mfa_secret,
)


class AdminBootstrapTest(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(
            _env_file=None,
            app_env="test",
            database_url="sqlite://",
            admin_jwt_secret="bootstrap-test-jwt-secret",
            admin_jwt_issuer="OAP Admin",
            admin_jwt_audience="oap-admin-bootstrap-test",
            admin_mfa_encryption_key=Fernet.generate_key().decode("ascii"),
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
        AdminUser.__table__.create(self.engine)
        AdminAuditLog.__table__.create(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.session_patch = patch(
            "app.services.admin_bootstrap_service.get_session",
            side_effect=self.sessions,
        )
        self.session_patch.start()

    def tearDown(self):
        self.session_patch.stop()
        self.engine.dispose()

    def _create(self, **overrides):
        values = {
            "email": " FIRST.Admin@Example.com ",
            "name": " First Admin ",
            "password": "password123",
        }
        values.update(overrides)
        return AdminBootstrapService(self.settings).create_first_admin(**values)

    def test_creates_normalized_super_admin_encrypted_mfa_and_audit(self):
        secret = pyotp.random_base32()
        with patch(
            "app.services.admin_bootstrap_service.generate_totp_secret",
            return_value=secret,
        ):
            result = self._create()

        with self.sessions() as session:
            admin = session.scalar(select(AdminUser))
            audit = session.scalar(select(AdminAuditLog))
            self.assertEqual(admin.email, "first.admin@example.com")
            self.assertEqual(admin.name, "First Admin")
            self.assertEqual(admin.role, "super_admin")
            self.assertTrue(admin.is_active)
            self.assertEqual(admin.session_version, 1)
            self.assertEqual(admin.failed_login_count, 0)
            self.assertIsNone(admin.locked_until)
            self.assertIsNone(admin.last_login_at)
            self.assertNotEqual(admin.mfa_secret_encrypted, secret)
            self.assertEqual(
                decrypt_mfa_secret(admin.mfa_secret_encrypted, self.settings),
                secret,
            )
            self.assertTrue(bcrypt.checkpw(b"password123", admin.password_hash.encode()))
            self.assertEqual(audit.action, "admin_created")
            self.assertEqual(audit.admin_id, admin.id)
            self.assertEqual(audit.target_type, "admin")
            self.assertEqual(audit.target_id, str(admin.id))
            self.assertEqual(audit.result, "success")
            self.assertEqual(audit.audit_metadata, {})
            self.assertNotIn("@", str(audit.audit_metadata))
        self.assertEqual(result.account_label, "first.admin@example.com")
        self.assertEqual(result.issuer, "OAP Admin")
        self.assertEqual(result.otpauth_uri.count("otpauth://"), 1)

    def test_rejects_invalid_inputs_with_existing_signup_policy(self):
        for changes in (
            {"email": "invalid"},
            {"name": "   "},
            {"password": "short"},
            {"password": "가" * 25},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self._create(**changes)
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count(AdminUser.id))), 0)

    def test_missing_or_invalid_security_settings_create_nothing(self):
        for settings in (
            Settings(_env_file=None, app_env="test", database_url="sqlite://"),
            self.settings.model_copy(update={"admin_mfa_encryption_key": "invalid"}),
        ):
            with self.subTest(settings=settings), self.assertRaises(
                AdminSecurityConfigurationError
            ):
                AdminBootstrapService(settings).create_first_admin(
                    email="admin@example.com",
                    name="Admin",
                    password="password123",
                )
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count(AdminUser.id))), 0)

    def test_existing_admin_is_rejected_without_disclosure(self):
        self._create()
        with self.assertRaises(AdminAlreadyExistsError) as raised:
            self._create(email="another@example.com")
        self.assertEqual(str(raised.exception), "")
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count(AdminUser.id))), 1)
            self.assertEqual(session.scalar(select(func.count(AdminAuditLog.id))), 1)

    def test_audit_failure_rolls_back_admin_and_does_not_return_uri(self):
        def fail_audit(*_):
            raise RuntimeError("audit failure")

        event.listen(AdminAuditLog, "before_insert", fail_audit)
        try:
            with self.assertRaises(AdminBootstrapError) as raised:
                self._create()
            self.assertNotIn("otpauth", str(raised.exception).lower())
        finally:
            event.remove(AdminAuditLog, "before_insert", fail_audit)
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count(AdminUser.id))), 0)
            self.assertEqual(session.scalar(select(func.count(AdminAuditLog.id))), 0)

    def test_security_operations_and_uri_follow_commit_order(self):
        calls = []
        original_hashpw = bcrypt.hashpw
        original_encrypt = bootstrap_module.encrypt_mfa_secret
        original_commit = self.sessions.class_.commit

        def hash_password(*args, **kwargs):
            calls.append("password_hash")
            return original_hashpw(*args, **kwargs)

        def generate_secret():
            calls.append("secret")
            return "JBSWY3DPEHPK3PXP"

        def encrypt_secret(*args, **kwargs):
            calls.append("encrypt")
            return original_encrypt(*args, **kwargs)

        def commit(session):
            calls.append("commit")
            return original_commit(session)

        def build_uri(*_):
            calls.append("uri")
            return "otpauth://test"

        with (
            patch("app.services.admin_bootstrap_service.bcrypt.hashpw", side_effect=hash_password),
            patch("app.services.admin_bootstrap_service.generate_totp_secret", side_effect=generate_secret),
            patch("app.services.admin_bootstrap_service.encrypt_mfa_secret", side_effect=encrypt_secret),
            patch.object(self.sessions.class_, "commit", autospec=True, side_effect=commit),
            patch("app.services.admin_bootstrap_service.build_totp_uri", side_effect=build_uri),
        ):
            self._create()

        self.assertEqual(calls, ["password_hash", "secret", "encrypt", "commit", "uri"])

    def test_commit_failure_never_builds_or_returns_uri(self):
        with (
            patch.object(self.sessions.class_, "commit", side_effect=RuntimeError("commit failed")),
            patch("app.services.admin_bootstrap_service.build_totp_uri") as build_uri,
            self.assertRaises(AdminBootstrapError) as raised,
        ):
            self._create()
        build_uri.assert_not_called()
        self.assertNotIn("otpauth", str(raised.exception).lower())
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count(AdminUser.id))), 0)
            self.assertEqual(session.scalar(select(func.count(AdminAuditLog.id))), 0)

    def test_existing_admin_stops_before_security_and_insert_work(self):
        self._create()
        with (
            patch("app.services.admin_bootstrap_service.bcrypt.hashpw") as hash_password,
            patch("app.services.admin_bootstrap_service.generate_totp_secret") as generate_secret,
            patch("app.services.admin_bootstrap_service.encrypt_mfa_secret") as encrypt_secret,
            patch("app.services.admin_bootstrap_service.build_totp_uri") as build_uri,
            self.assertRaises(AdminAlreadyExistsError),
        ):
            self._create(email="second@example.com")
        hash_password.assert_not_called()
        generate_secret.assert_not_called()
        encrypt_secret.assert_not_called()
        build_uri.assert_not_called()
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count(AdminUser.id))), 1)
            self.assertEqual(session.scalar(select(func.count(AdminAuditLog.id))), 1)

    def test_cli_uses_getpass_and_prints_uri_once_after_success(self):
        result = AdminBootstrapResult(
            "admin@example.com",
            "OAP Admin",
            "otpauth://totp/OAP%20Admin:admin@example.com?secret=test",
        )
        output = io.StringIO()
        with (
            patch.object(sys, "argv", ["create_admin"]),
            patch("builtins.input", side_effect=["admin@example.com", "Admin"]),
            patch("getpass.getpass", side_effect=["password123", "password123"]) as hidden,
            patch(
                "app.cli.create_admin.AdminBootstrapService.create_first_admin",
                return_value=result,
            ) as create,
            redirect_stdout(output),
        ):
            self.assertEqual(main(), 0)
        self.assertEqual(hidden.call_count, 2)
        self.assertEqual(output.getvalue().count("otpauth://"), 1)
        self.assertNotIn("password123", output.getvalue())
        create.assert_called_once()

    def test_cli_mismatch_and_failure_do_not_print_password_or_uri(self):
        for error in (None, AdminBootstrapError()):
            stdout, stderr = io.StringIO(), io.StringIO()
            service = patch(
                "app.cli.create_admin.AdminBootstrapService.create_first_admin",
                side_effect=error,
            )
            passwords = ["password123", "different"] if error is None else ["password123", "password123"]
            with (
                patch.object(sys, "argv", ["create_admin"]),
                patch("builtins.input", side_effect=["admin@example.com", "Admin"]),
                patch("getpass.getpass", side_effect=passwords),
                service as create,
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                self.assertEqual(main(), 1)
            self.assertNotIn("password123", stdout.getvalue() + stderr.getvalue())
            self.assertNotIn("otpauth", stdout.getvalue() + stderr.getvalue())
            if error is None:
                create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
