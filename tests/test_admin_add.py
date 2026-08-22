import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from unittest.mock import patch

import bcrypt
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.services.admin_add_service as add_module
from app.cli.add_admin import main
from app.core.config import Settings
from app.models.admin import AdminAuditLog, AdminUser
from app.services.admin_add_service import (
    AdminAddError,
    AdminAddResult,
    AdminAddService,
    AdminEmailExistsError,
    InvalidAdminRoleError,
)
from app.services.admin_security import decrypt_mfa_secret


class AdminAddTest(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(
            _env_file=None,
            app_env="test",
            database_url="sqlite://",
            admin_jwt_secret="add-admin-test-jwt-secret",
            admin_jwt_issuer="OAP Admin",
            admin_jwt_audience="oap-admin-add-test",
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
            "app.services.admin_add_service.get_session", side_effect=self.sessions
        )
        self.session_patch.start()

    def tearDown(self):
        self.session_patch.stop()
        self.engine.dispose()

    def _create(self, **overrides):
        values = {
            "email": " Added.Admin@Example.com ",
            "name": " Added Admin ",
            "password": "password123",
            "role": "analyst",
        }
        values.update(overrides)
        return AdminAddService(self.settings).create_admin(**values)

    def test_creates_normalized_admin_with_encrypted_mfa_and_same_transaction_audit(self):
        secret = "JBSWY3DPEHPK3PXP"
        with patch("app.services.admin_add_service.generate_totp_secret", return_value=secret):
            result = self._create()

        with self.sessions() as session:
            admin = session.scalar(select(AdminUser))
            audit = session.scalar(select(AdminAuditLog))
            self.assertEqual(admin.email, "added.admin@example.com")
            self.assertEqual(admin.name, "Added Admin")
            self.assertTrue(admin.is_active)
            self.assertEqual(admin.session_version, 1)
            self.assertEqual(admin.failed_login_count, 0)
            self.assertNotEqual(admin.mfa_secret_encrypted, secret)
            self.assertEqual(decrypt_mfa_secret(admin.mfa_secret_encrypted, self.settings), secret)
            self.assertTrue(bcrypt.checkpw(b"password123", admin.password_hash.encode()))
            self.assertEqual(audit.admin_id, admin.id)
            self.assertEqual(audit.action, "admin_created")
            self.assertEqual(audit.audit_metadata, {})
            self.assertNotIn(secret, str(audit.audit_metadata))
        self.assertEqual(result.account_label, "added.admin@example.com")

    def test_creates_each_role(self):
        for role in ("analyst", "support", "super_admin"):
            with self.subTest(role=role):
                self._create(email=f"{role}@example.com", role=role)
        with self.sessions() as session:
            self.assertEqual(set(session.scalars(select(AdminUser.role))), {"analyst", "support", "super_admin"})

    def test_duplicate_email_is_rejected_before_secret_work(self):
        self._create()
        with (
            patch("app.services.admin_add_service.generate_totp_secret") as generate,
            self.assertRaises(AdminEmailExistsError),
        ):
            self._create(email="added.admin@example.com")
        generate.assert_not_called()
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count(AdminUser.id))), 1)
            self.assertEqual(session.scalar(select(func.count(AdminAuditLog.id))), 1)

    def test_invalid_role_creates_nothing(self):
        with self.assertRaises(InvalidAdminRoleError):
            self._create(role="owner")
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count(AdminUser.id))), 0)

    def test_audit_failure_rolls_back_everything_and_never_builds_uri(self):
        def fail_audit(*_):
            raise RuntimeError("audit failure")

        event.listen(AdminAuditLog, "before_insert", fail_audit)
        try:
            with (
                patch("app.services.admin_add_service.build_totp_uri") as build_uri,
                self.assertRaises(AdminAddError),
            ):
                self._create()
            build_uri.assert_not_called()
        finally:
            event.remove(AdminAuditLog, "before_insert", fail_audit)
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count(AdminUser.id))), 0)
            self.assertEqual(session.scalar(select(func.count(AdminAuditLog.id))), 0)

    def test_commit_failure_rolls_back_and_never_builds_uri(self):
        with (
            patch.object(self.sessions.class_, "commit", side_effect=RuntimeError("failed")),
            patch("app.services.admin_add_service.build_totp_uri") as build_uri,
            self.assertRaises(AdminAddError),
        ):
            self._create()
        build_uri.assert_not_called()
        with self.sessions() as session:
            self.assertEqual(session.scalar(select(func.count(AdminUser.id))), 0)
            self.assertEqual(session.scalar(select(func.count(AdminAuditLog.id))), 0)

    def test_uri_is_built_only_after_commit(self):
        calls = []
        original_commit = self.sessions.class_.commit

        def commit(session):
            calls.append("commit")
            return original_commit(session)

        def build_uri(*_):
            calls.append("uri")
            return "otpauth://test"

        with (
            patch.object(self.sessions.class_, "commit", autospec=True, side_effect=commit),
            patch("app.services.admin_add_service.build_totp_uri", side_effect=build_uri),
        ):
            self._create()
        self.assertEqual(calls, ["commit", "uri"])

    def test_cli_password_mismatch_does_no_db_work(self):
        with (
            patch.object(sys, "argv", ["add_admin"]),
            patch("builtins.input", side_effect=["admin@example.com", "Admin"]),
            patch("getpass.getpass", side_effect=["password123", "different"]),
            patch("app.cli.add_admin.AdminAddService.create_admin") as create,
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(main(), 1)
        create.assert_not_called()

    def test_cli_success_prints_uri_once_without_password(self):
        result = AdminAddResult("admin@example.com", "OAP Admin", "otpauth://test")
        output = io.StringIO()
        with (
            patch.object(sys, "argv", ["add_admin"]),
            patch("builtins.input", side_effect=["admin@example.com", "Admin", "support"]),
            patch("getpass.getpass", side_effect=["password123", "password123"]),
            patch("app.cli.add_admin.AdminAddService.create_admin", return_value=result),
            redirect_stdout(output),
        ):
            self.assertEqual(main(), 0)
        self.assertEqual(output.getvalue().count("otpauth://"), 1)
        self.assertNotIn("password123", output.getvalue())


if __name__ == "__main__":
    unittest.main()
