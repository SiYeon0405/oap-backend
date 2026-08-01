import logging
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.ai import interview_question_ai, openai_client, report_ai
from app.core.config import Settings, get_openai_api_key
from app.services.embedding_service import EmbeddingService


class OpenAIKeyResolutionTest(unittest.TestCase):
    def settings(self, app_env, openai_api_key=None):
        database_url = (
            "postgresql+psycopg://user:password@db.project.supabase.co/postgres"
            if app_env == "production"
            else "sqlite://"
        )
        return Settings(
            _env_file=None,
            app_env=app_env,
            database_url=database_url,
            openai_api_key=openai_api_key,
        )

    def local_key(self, env_file_key, os_key=None):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                f"OPENAI_API_KEY={env_file_key}\n",
                encoding="utf-8",
            )
            environment = {} if os_key is None else {"OPENAI_API_KEY": os_key}
            with (
                patch.dict(os.environ, environment, clear=True),
                patch("app.core.config.ENV_FILE", env_file),
            ):
                return get_openai_api_key(self.settings("local"))

    def test_local_uses_project_env_key(self):
        self.assertEqual(self.local_key("sk-local"), "sk-local")

    def test_local_allows_matching_os_and_env_keys(self):
        self.assertEqual(self.local_key("sk-same", "sk-same"), "sk-same")

    def test_local_conflict_warns_and_uses_project_env_key(self):
        with self.assertLogs("app.core.config", logging.WARNING) as logs:
            selected = self.local_key("sk-project-env", "sk-os")
        self.assertEqual(selected, "sk-project-env")
        self.assertNotIn("sk-project-env", " ".join(logs.output))
        self.assertNotIn("sk-os", " ".join(logs.output))

    def test_production_uses_os_key(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-production"}, clear=True):
            selected = get_openai_api_key(
                self.settings("production", "sk-settings")
            )
        self.assertEqual(selected, "sk-production")

    def test_production_rejects_missing_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "OPENAI_API_KEY"):
                get_openai_api_key(self.settings("production", "sk-env-file"))

    def test_production_rejects_whitespace_key(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "   "}, clear=True):
            with self.assertRaisesRegex(ValueError, "OPENAI_API_KEY"):
                get_openai_api_key(self.settings("production"))

    def test_test_environment_uses_injected_key(self):
        selected = get_openai_api_key(self.settings("test", "sk-test-fake"))
        self.assertEqual(selected, "sk-test-fake")


class OpenAIClientIntegrationTest(unittest.TestCase):
    def tearDown(self):
        openai_client.get_openai_client.cache_clear()

    def test_factory_reuses_one_client_and_explicit_key(self):
        fake_client = object()
        with (
            patch("app.ai.openai_client.get_openai_api_key", return_value="sk-safe"),
            patch("app.ai.openai_client.OpenAI", return_value=fake_client) as constructor,
        ):
            first = openai_client.get_openai_client()
            second = openai_client.get_openai_client()
        self.assertIs(first, second)
        constructor.assert_called_once_with(api_key="sk-safe")

    def test_report_uses_common_client(self):
        response = SimpleNamespace(output_text="{}")
        client = SimpleNamespace(
            responses=SimpleNamespace(create=MagicMock(return_value=response))
        )
        request = SimpleNamespace(
            service_name="service",
            one_line_description="description",
            industry="industry",
            main_question="question",
        )
        with patch("app.ai.report_ai.get_openai_client", return_value=client) as factory:
            report_ai._request_analysis_report(request, evidence_context="")
        factory.assert_called_once_with()

    def test_interview_uses_common_client(self):
        response = SimpleNamespace(output_text="새 질문인가요?")
        client = SimpleNamespace(
            responses=SimpleNamespace(create=MagicMock(return_value=response))
        )
        with patch(
            "app.ai.interview_question_ai.get_openai_client",
            return_value=client,
        ) as factory:
            result = interview_question_ai.generate_next_question(
                SimpleNamespace(name="service"),
                [],
            )
        self.assertEqual(result, "새 질문인가요?")
        factory.assert_called_once_with()

    def test_interview_fallback_log_does_not_include_key(self):
        secret = "sk-secret-must-not-appear"
        error = RuntimeError(secret)
        with (
            patch(
                "app.ai.interview_question_ai.get_openai_client",
                side_effect=error,
            ),
            self.assertLogs(
                "app.ai.interview_question_ai",
                logging.WARNING,
            ) as logs,
        ):
            result = interview_question_ai.generate_next_question(
                SimpleNamespace(name="service"),
                [],
            )
        self.assertTrue(result)
        self.assertNotIn(secret, " ".join(logs.output))

    def test_embedding_service_uses_common_client(self):
        client = object()
        with patch(
            "app.services.embedding_service.get_openai_client",
            return_value=client,
        ) as factory:
            service = EmbeddingService()
        self.assertIs(service.client, client)
        factory.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
