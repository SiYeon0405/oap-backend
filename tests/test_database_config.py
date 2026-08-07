import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pydantic import ValidationError
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import (
    ENV_FILE,
    Settings,
    get_app_env,
    get_cors_allowed_origins,
    get_database_url,
)
from app.database.session import get_database_target


class DatabaseConfigTest(unittest.TestCase):
    def build_settings(self, **values):
        return Settings(_env_file=None, **values)

    def assert_invalid(self, **values):
        with self.assertRaises(ValidationError):
            self.build_settings(**values)

    def test_production_requires_database_url(self):
        self.assert_invalid(app_env="production")

    def test_production_rejects_localhost(self):
        self.assert_invalid(
            app_env="production",
            database_url="postgresql+psycopg://user:secret@localhost/db",
        )

    def test_production_rejects_ipv4_loopback(self):
        self.assert_invalid(
            app_env="production",
            database_url="postgresql+psycopg://user:secret@127.0.0.1/db",
        )

    def test_production_rejects_non_supabase_postgresql(self):
        self.assert_invalid(
            app_env="production",
            database_url="postgresql+psycopg://user:secret@db.example.com/db",
        )

    def test_production_allows_supabase_direct_host(self):
        settings = self.build_settings(
            app_env="production",
            database_url="postgresql+psycopg://user:secret@db.project.supabase.co/postgres",
        )
        self.assertEqual(settings.app_env, "production")

    def test_production_allows_supabase_pooler_host(self):
        settings = self.build_settings(
            app_env="production",
            database_url=(
                "postgresql+psycopg://user:secret@"
                "aws-0-ap-northeast-2.pooler.supabase.com:5432/postgres"
            ),
        )
        self.assertEqual(settings.app_env, "production")

    def test_local_allows_localhost(self):
        settings = self.build_settings(
            app_env="local",
            database_url="postgresql+psycopg://user:secret@localhost/oap",
        )
        self.assertEqual(settings.app_env, "local")

    def test_test_database_url_is_explicitly_selected(self):
        settings = self.build_settings(
            app_env="test",
            test_database_url="sqlite://",
        )
        self.assertEqual(settings.database_url, "sqlite://")

    def test_database_target_omits_credentials_and_query(self):
        settings = self.build_settings(
            app_env="production",
            database_url=(
                "postgresql+psycopg://user:secret@db.project.supabase.co:5432/"
                "postgres?sslmode=require"
            ),
        )
        with patch("app.database.session.get_database_url", return_value=get_database_url(settings)):
            target = get_database_target()

        self.assertEqual(
            target,
            {
                "driver": "postgresql+psycopg",
                "host": "db.project.supabase.co",
                "port": 5432,
                "database": "postgres",
            },
        )
        self.assertNotIn("user", target)
        self.assertNotIn("password", target)
        self.assertNotIn("query", target)

    def test_health_response_does_not_expose_credentials(self):
        fake_session = MagicMock()
        fake_session.__enter__.return_value = fake_session
        target = {
            "driver": "postgresql+psycopg",
            "host": "db.project.supabase.co",
            "port": 5432,
            "database": "postgres",
        }
        with (
            patch("app.api.health.get_session", return_value=fake_session),
            patch("app.api.health.get_database_target", return_value=target),
        ):
            from app.api.health import database_health_check

            response = database_health_check()

        self.assertEqual(response["database"], "connected")
        self.assertEqual(response["databaseName"], "postgres")
        self.assertNotIn("secret", str(response))
        self.assertNotIn("user", response)
        self.assertNotIn("password", response)
        self.assertNotIn("query", response)

    def test_env_file_is_fixed_to_project_root(self):
        self.assertTrue(Path(ENV_FILE).is_absolute())
        self.assertEqual(Path(ENV_FILE).name, ".env")

    def test_cors_origins_default_to_local_development_ports(self):
        with patch.dict("os.environ", {}, clear=True), patch(
            "app.core.config.dotenv_values", return_value={}
        ):
            self.assertEqual(
                get_cors_allowed_origins(),
                [
                    "http://localhost:3000",
                    "http://localhost:3001",
                    "http://localhost:5173",
                ],
            )

    def test_cors_origins_parse_trim_normalize_and_deduplicate(self):
        with patch.dict(
            "os.environ",
            {
                "CORS_ALLOWED_ORIGINS": (
                    " https://frontend.example/ , ,"
                    "https://frontend.example,http://localhost:3000/ "
                )
            },
            clear=True,
        ):
            self.assertEqual(
                get_cors_allowed_origins(),
                ["https://frontend.example", "http://localhost:3000"],
            )

    def test_cors_origins_reject_wildcard(self):
        with patch.dict(
            "os.environ", {"CORS_ALLOWED_ORIGINS": "*"}, clear=True
        ):
            with self.assertRaisesRegex(ValueError, "wildcard"):
                get_cors_allowed_origins()

    def test_cors_middleware_and_sensitive_requests_share_configuration(self):
        from app.main import app

        cors_middleware = next(
            middleware
            for middleware in app.user_middleware
            if middleware.cls.__name__ == "CORSMiddleware"
        )
        self.assertEqual(
            cors_middleware.kwargs["allow_origins"],
            get_cors_allowed_origins(),
        )
        self.assertTrue(cors_middleware.kwargs["allow_credentials"])

    def test_production_disables_api_documentation_routes(self):
        from app.main import get_documentation_options

        with patch.dict("os.environ", {"APP_ENV": "production"}):
            app_env = get_app_env()
        test_app = FastAPI(**get_documentation_options(app_env))
        with TestClient(test_app) as client:
            for path in ("/docs", "/redoc", "/openapi.json"):
                with self.subTest(path=path):
                    self.assertEqual(client.get(path).status_code, 404)

    def test_local_keeps_api_documentation_routes(self):
        from app.main import get_documentation_options

        with patch.dict("os.environ", {"APP_ENV": "local"}):
            app_env = get_app_env()
        test_app = FastAPI(**get_documentation_options(app_env))
        with TestClient(test_app) as client:
            for path in ("/docs", "/redoc", "/openapi.json"):
                with self.subTest(path=path):
                    self.assertEqual(client.get(path).status_code, 200)

    def test_alembic_and_application_use_same_database_url_contract(self):
        alembic_env = Path("alembic/env.py").read_text(encoding="utf-8")
        session_module = Path("app/database/session.py").read_text(encoding="utf-8")
        self.assertIn("get_database_url()", alembic_env)
        self.assertIn("get_database_url()", session_module)

    def test_production_startup_verifies_connection_without_logging_secrets(self):
        from app.main import validate_production_database

        settings = self.build_settings(
            app_env="production",
            database_url=(
                "postgresql+psycopg://user:secret@"
                "db.project.supabase.co:5432/postgres?sslmode=require"
            ),
        )
        target = {
            "driver": "postgresql+psycopg",
            "host": "db.project.supabase.co",
            "port": 5432,
            "database": "postgres",
        }
        with (
            patch("app.main.get_settings", return_value=settings),
            patch("app.main.verify_database_connection") as verify,
            patch("app.main.get_database_target", return_value=target),
            patch("app.main.logger.info") as log_info,
        ):
            validate_production_database()

        verify.assert_called_once_with()
        logged_values = log_info.call_args.args[1:]
        self.assertNotIn("user", logged_values)
        self.assertNotIn("secret", logged_values)
        self.assertNotIn("sslmode", str(logged_values))


if __name__ == "__main__":
    unittest.main()
