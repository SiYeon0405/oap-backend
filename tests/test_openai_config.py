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
from app.services.interview_message_service import InterviewMessageService


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
        question = (
            "누가 이 서비스를 가장 많이 쓸까요? "
            "(예: 혼자 가게를 운영하는 사장님) 잘 모르겠으면 넘어가도 됩니다."
        )
        response = SimpleNamespace(output_text=question)
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
        self.assertEqual(result, question)
        factory.assert_called_once_with()

        request_input = client.responses.create.call_args.kwargs["input"]
        system_prompt = request_input[0]["content"]
        self.assertIn("한 질문에서는 한 가지 내용만", system_prompt)
        self.assertIn("짧고 구체적인 예시", system_prompt)
        self.assertIn("잘 모르겠으면 넘어가도", system_prompt)

    def test_interview_fallback_log_does_not_include_key(self):
        secret = "sk-secret-must-not-appear"

        class AuthenticationError(Exception):
            body = {"error": {"code": "invalid_api_key"}}

        error = AuthenticationError(secret)
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
        self.assertIn("(예:", result)
        self.assertIn("잘 모르겠으면", result)
        log_output = " ".join(logs.output)
        self.assertIn("error_type=AuthenticationError", log_output)
        self.assertIn("error_code=invalid_api_key", log_output)
        self.assertNotIn(secret, log_output)

    def test_all_interview_fallback_questions_are_easy_to_answer(self):
        self.assertEqual(len(interview_question_ai.FALLBACK_QUESTIONS), 5)
        for question in interview_question_ai.FALLBACK_QUESTIONS:
            with self.subTest(question=question):
                self.assertEqual(question.count("?"), 1)
                self.assertIn("(예:", question)
                self.assertIn("잘 모르겠으면", question)

    def test_interview_fallback_follows_five_unique_steps(self):
        messages = []
        generated = []
        for question in interview_question_ai.FALLBACK_QUESTIONS:
            next_question = interview_question_ai._fallback_question(messages)
            generated.append(next_question)
            messages.append(SimpleNamespace(role="AI", content=next_question))
            messages.append(SimpleNamespace(role="USER", content="잘 모르겠어요"))

        self.assertEqual(generated, interview_question_ai.FALLBACK_QUESTIONS)
        self.assertEqual(len(set(generated)), 5)

    def test_interview_completes_after_exactly_five_answers(self):
        messages = [
            SimpleNamespace(role="USER", content=f"답변 {index}")
            for index in range(1, 5)
        ]
        analysis_request = SimpleNamespace(
            id=1,
            status="INTERVIEWING",
            interview_completed=False,
        )
        repository = MagicMock()
        repository.find_max_message_order.return_value = len(messages)
        repository.find_messages.return_value = messages
        repository.save_message.side_effect = lambda session, message: messages.append(
            message
        )
        session = MagicMock()
        session_context = MagicMock()
        session_context.__enter__.return_value = session
        report_result = SimpleNamespace(status="COMPLETED")

        with (
            patch(
                "app.services.interview_message_service.get_session",
                return_value=session_context,
            ),
            patch(
                "app.services.interview_message_service.AnalysisRequestService.get_owned_or_404",
                return_value=analysis_request,
            ),
            patch(
                "app.services.interview_message_service.AnalysisReportService.start_analysis",
                return_value=report_result,
            ) as start_analysis,
        ):
            result = InterviewMessageService(repository).save_answer(
                1,
                SimpleNamespace(answer="다섯 번째 답변"),
                1,
            )

        self.assertTrue(result.interviewCompleted)
        self.assertEqual(result.nextQuestion, "")
        self.assertTrue(analysis_request.interview_completed)
        start_analysis.assert_called_once_with(1)

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
