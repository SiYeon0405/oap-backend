import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.main import app
from app.models.base import Base
from app.models.search_keyword import Keyword, KeywordMetric
from app.repositories.keyword_repository import KeywordRepository
from app.services.analysis_request_service import AnalysisRequestService
from app.services.keyword_collection_service import (
    KeywordCollectionService,
    build_seeds,
    normalize_keyword,
    parse_count,
)
from app.services.naver_searchad_client import NaverSearchAdClient, NaverSearchAdError


class SearchPipelineTest(unittest.TestCase):
    def tearDown(self):
        app.dependency_overrides.clear()

    def test_normalize_seed_and_count_contracts(self):
        self.assertEqual(normalize_keyword("스타트업 마케팅"), "스타트업마케팅")
        seeds = build_seeds({"문제": "스타트업 마케팅", "해결수단": "마케팅 가이드"}, "OAP", "IT/SaaS")
        self.assertIn(("SOLUTION", "스타트업 마케팅 툴"), seeds)
        self.assertIn(("RECOMMENDATION", "스타트업 마케팅 추천"), seeds)
        self.assertNotIn("후회", " ".join(value for _, value in seeds))
        self.assertEqual(parse_count("< 10"), 5)

    def test_client_rejects_six_keywords(self):
        with self.assertRaises(ValueError):
            NaverSearchAdClient().fetch_keywords([str(value) for value in range(6)])

    @patch("app.services.naver_searchad_client.get_settings")
    @patch("app.services.naver_searchad_client.time.sleep")
    def test_client_retries_429_then_succeeds(self, sleep, get_settings):
        get_settings.return_value = SimpleNamespace(
            naver_ad_api_key="key", naver_ad_secret_key="secret", naver_ad_customer_id="customer"
        )
        request = httpx.Request("GET", "https://api.searchad.naver.com/keywordstool")
        rate_limited = httpx.Response(429, headers={"Retry-After": "3"}, request=request)
        success = httpx.Response(200, json={"keywordList": [{"relKeyword": "OAP"}]}, request=request)
        http_client = MagicMock()
        http_client.get.side_effect = [rate_limited, success]

        rows = NaverSearchAdClient(http_client).fetch_keywords(["OAP"])

        self.assertEqual(rows, [{"relKeyword": "OAP"}])
        self.assertEqual(http_client.get.call_count, 2)
        sleep.assert_called_once_with(3.0)

    @patch("app.services.naver_searchad_client.get_settings")
    @patch("app.services.naver_searchad_client.time.sleep")
    def test_client_ignores_invalid_retry_after(self, sleep, get_settings):
        get_settings.return_value = SimpleNamespace(
            naver_ad_api_key="key", naver_ad_secret_key="secret", naver_ad_customer_id="customer"
        )
        request = httpx.Request("GET", "https://api.searchad.naver.com/keywordstool")
        for retry_after in ("-1", "NaN", "Infinity", "-inf", "invalid-string"):
            with self.subTest(retry_after=retry_after):
                http_client = MagicMock()
                http_client.get.side_effect = [
                    httpx.Response(429, headers={"Retry-After": retry_after}, request=request),
                    httpx.Response(200, json={"keywordList": [{"relKeyword": "OAP"}]}, request=request),
                ]

                NaverSearchAdClient(http_client).fetch_keywords(["OAP"])

                sleep.assert_called_once_with(1.0)
                sleep.reset_mock()

    @patch("app.services.naver_searchad_client.get_settings")
    @patch("app.services.naver_searchad_client.time.sleep")
    def test_client_stops_after_three_429_responses(self, sleep, get_settings):
        get_settings.return_value = SimpleNamespace(
            naver_ad_api_key="key", naver_ad_secret_key="secret", naver_ad_customer_id="customer"
        )
        request = httpx.Request("GET", "https://api.searchad.naver.com/keywordstool")
        http_client = MagicMock()
        http_client.get.side_effect = [
            httpx.Response(429, request=request),
            httpx.Response(429, request=request),
            httpx.Response(429, request=request),
        ]

        with self.assertRaises(NaverSearchAdError):
            NaverSearchAdClient(http_client).fetch_keywords(["OAP"])

        self.assertEqual(http_client.get.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1.0, 2.0])

    @patch("app.services.naver_searchad_client.get_settings")
    @patch("app.services.naver_searchad_client.time.sleep")
    def test_client_does_not_retry_other_http_errors(self, sleep, get_settings):
        get_settings.return_value = SimpleNamespace(
            naver_ad_api_key="key", naver_ad_secret_key="secret", naver_ad_customer_id="customer"
        )
        for status_code in (401, 403):
            with self.subTest(status_code=status_code):
                request = httpx.Request("GET", "https://api.searchad.naver.com/keywordstool")
                http_client = MagicMock()
                http_client.get.return_value = httpx.Response(status_code, request=request)

                with self.assertRaises(NaverSearchAdError):
                    NaverSearchAdClient(http_client).fetch_keywords(["OAP"])

                http_client.get.assert_called_once()
        sleep.assert_not_called()

    def test_collect_deduplicates_rows_appends_metrics_and_sets_time(self):
        repository = MagicMock()
        repository.add_metrics.side_effect = lambda session, rows, request_id: rows
        client = MagicMock()
        client.fetch_keywords.side_effect = [
            [
                {"relKeyword": "스타트업 마케팅", "monthlyPcQcCnt": "< 10", "monthlyMobileQcCnt": 20, "compIdx": "중간"},
                {"relKeyword": "스타트업마케팅", "monthlyPcQcCnt": 10, "monthlyMobileQcCnt": 20, "compIdx": "중간"},
            ],
            [],
            [],
            [],
            [],
            [],
        ]
        session = MagicMock()
        session.__enter__.return_value = session
        service = KeywordCollectionService(
            repository=repository,
            naver_client=client,
            extractor=lambda *_: {"문제": "스타트업 마케팅", "해결수단": "마케팅 가이드"},
        )
        with patch("app.services.keyword_collection_service.get_session", return_value=session):
            rows = service.collect(101, "OAP", "IT/SaaS", "설명")

        self.assertEqual(
            [call.args[0] for call in client.fetch_keywords.call_args_list],
            [["스타트업 마케팅"], ["스타트업 마케팅 툴"], ["스타트업 마케팅 대행사"],
             ["스타트업 마케팅 추천"], ["스타트업 마케팅 비용"], ["OAP"]],
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["metric"]["total_count"], 30)
        self.assertEqual(rows[0]["metric"]["pc_count_raw"], "10")
        self.assertEqual(rows[0]["seed_type"], "PROBLEM")
        self.assertIsNotNone(rows[0]["metric"]["collected_at"])
        self.assertEqual(repository.add_metrics.call_args.args[2], 101)

    def test_repository_reuses_keyword_and_appends_metric(self):
        engine = create_engine("sqlite://")
        Base.metadata.create_all(
            engine,
            tables=[Keyword.__table__, KeywordMetric.__table__],
        )
        row = {
            "keyword": "스타트업마케팅",
            "keyword_raw": "스타트업 마케팅",
            "seed_type": "PROBLEM",
            "metric": {
                "pc_count_raw": "< 10",
                "mobile_count_raw": "20",
                "pc_count": 5,
                "mobile_count": 20,
                "total_count": 25,
                "comp_idx": "중간",
                "source": "naver_searchad_keywordstool",
                "collected_at": datetime.now(timezone.utc),
            },
        }
        repository = KeywordRepository()
        with Session(engine) as session:
            repository.add_metrics(session, [row], 101)
            row["seed_type"] = "ALTERNATIVE"
            repository.add_metrics(session, [row], 202)
            keyword_id = session.scalar(
                select(Keyword.id).where(Keyword.keyword == "스타트업마케팅")
            )
            session.add(
                KeywordMetric(
                    keyword_id=keyword_id,
                    pc_count_raw="< 10",
                    mobile_count_raw="< 10",
                    pc_count=5,
                    mobile_count=5,
                    total_count=10,
                    source="naver_searchad_keywordstool",
                    collected_at=datetime.now(timezone.utc),
                )
            )
            session.commit()
            self.assertEqual(session.scalar(select(func.count()).select_from(Keyword)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(KeywordMetric)), 3)
            metrics = session.scalars(
                select(KeywordMetric)
                .where(KeywordMetric.analysis_request_id.is_not(None))
                .order_by(KeywordMetric.id)
            ).all()
            self.assertEqual(
                [(metric.analysis_request_id, metric.seed_type) for metric in metrics],
                [(101, "PROBLEM"), (202, "ALTERNATIVE")],
            )
            self.assertEqual(metrics[0].pc_count_raw, "< 10")
            self.assertEqual(metrics[0].mobile_count_raw, "20")
            self.assertEqual(metrics[0].total_count, 25)
            request_101_metrics = session.scalars(
                select(KeywordMetric).where(KeywordMetric.analysis_request_id == 101)
            ).all()
            self.assertEqual(len(request_101_metrics), 1)
            self.assertTrue(
                all(metric.analysis_request_id == 101 for metric in request_101_metrics)
            )
            repository_rows = repository.find_metrics_by_analysis_request(session, 101)
            self.assertEqual(len(repository_rows), 1)
            self.assertEqual(repository_rows[0][0].analysis_request_id, 101)
            self.assertEqual(repository_rows[0][1].keyword, "스타트업마케팅")
            legacy_metric = session.scalar(
                select(KeywordMetric).where(KeywordMetric.analysis_request_id.is_(None))
            )
            self.assertIsNone(legacy_metric.seed_type)
            self.assertEqual(legacy_metric.pc_count_raw, "< 10")

    def test_repository_batches_keywords_and_keeps_metrics_per_seed(self):
        engine = create_engine("sqlite://")
        Base.metadata.create_all(
            engine,
            tables=[Keyword.__table__, KeywordMetric.__table__],
        )
        keyword_selects = []

        def count_keyword_selects(_conn, _cursor, statement, _parameters, _context, _many):
            if statement.lstrip().upper().startswith("SELECT") and "FROM keywords" in statement:
                keyword_selects.append(statement)

        event.listen(engine, "before_cursor_execute", count_keyword_selects)
        collected_at = datetime.now(timezone.utc)
        rows = [
            {
                "keyword": keyword,
                "keyword_raw": keyword_raw,
                "seed_type": seed_type,
                "metric": {
                    "pc_count_raw": "< 10",
                    "mobile_count_raw": "20",
                    "pc_count": 5,
                    "mobile_count": 20,
                    "total_count": 25,
                    "comp_idx": "MEDIUM",
                    "source": "naver_searchad_keywordstool",
                    "collected_at": collected_at,
                },
            }
            for keyword, keyword_raw, seed_type in (
                ("searchads", "search ads", "PROBLEM"),
                ("agency", "agency", "SOLUTION"),
                ("searchads", "search ads", "BRAND"),
            )
        ]

        with Session(engine) as session:
            metrics = KeywordRepository().add_metrics(session, rows, 303)

            self.assertEqual(len(keyword_selects), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(Keyword)), 2)
            self.assertEqual(len(metrics), 3)
            self.assertTrue(all(metric.analysis_request_id == 303 for metric in metrics))
            self.assertEqual([metric.seed_type for metric in metrics], ["PROBLEM", "SOLUTION", "BRAND"])
            self.assertTrue(all(metric.pc_count_raw == "< 10" for metric in metrics))
            self.assertEqual(metrics[0].keyword_id, metrics[2].keyword_id)

    def test_empty_response_is_a_visible_warning(self):
        response = MagicMock()
        response.json.return_value = {"keywordList": []}
        response.raise_for_status.return_value = None
        http_client = MagicMock()
        http_client.get.return_value = response
        settings = SimpleNamespace(
            naver_ad_api_key="key", naver_ad_secret_key="secret", naver_ad_customer_id="customer"
        )
        with (
            patch("app.services.naver_searchad_client.get_settings", return_value=settings),
            self.assertLogs("app.services.naver_searchad_client", level="WARNING"),
        ):
            self.assertEqual(NaverSearchAdClient(http_client).fetch_keywords(["OAP"]), [])

    def test_analysis_request_survives_keyword_failure(self):
        repository = MagicMock()
        repository.save.side_effect = lambda session, request: setattr(request, "id", 7) or request
        interview_repository = MagicMock()
        collection = MagicMock()
        collection.collect.side_effect = NaverSearchAdError("down")
        session = MagicMock()
        session.__enter__.return_value = session
        request = SimpleNamespace(serviceName="OAP", oneLineDescription="설명", industry="IT/SaaS", mainQuestion="질문")
        service = AnalysisRequestService(repository, interview_repository, collection)
        with (
            patch("app.services.analysis_request_service.get_session", return_value=session),
        ):
            saved = service.create(request, 1)

        with (
            patch("app.services.analysis_request_service.get_session", return_value=session),
            self.assertLogs("app.services.analysis_request_service", level="WARNING"),
        ):
            service.collect_keywords(
                saved.id,
                saved.service_name,
                saved.industry,
                saved.one_line_description,
            )

        self.assertEqual(saved.id, 7)
        self.assertEqual(saved.keyword_collection_status, "PENDING")
        collection.collect.assert_called_once_with(7, "OAP", "IT/SaaS", "설명")
        interview_repository.save_message.assert_called_once()

        self.assertEqual(
            [call.args[2] for call in repository.update_keyword_collection_status.call_args_list],
            ["COLLECTING", "FAILED"],
        )

    def test_keyword_collection_status_completes_even_when_empty(self):
        repository = MagicMock()
        collection = MagicMock()
        collection.collect.return_value = []
        session = MagicMock()
        session.__enter__.return_value = session
        service = AnalysisRequestService(
            repository=repository,
            interview_repository=MagicMock(),
            keyword_collection_service=collection,
        )

        with patch("app.services.analysis_request_service.get_session", return_value=session):
            service.collect_keywords(8, "OAP", "IT/SaaS", "description")

        self.assertEqual(
            [call.args[2] for call in repository.update_keyword_collection_status.call_args_list],
            ["COLLECTING", "COMPLETED"],
        )

    def test_keyword_collection_status_fails_for_each_pipeline_stage(self):
        for failure in (
            RuntimeError("extractor failed"),
            NaverSearchAdError("naver failed"),
            RuntimeError("repository failed"),
        ):
            with self.subTest(failure=str(failure)):
                repository = MagicMock()
                collection = MagicMock()
                collection.collect.side_effect = failure
                session = MagicMock()
                session.__enter__.return_value = session
                service = AnalysisRequestService(
                    repository=repository,
                    interview_repository=MagicMock(),
                    keyword_collection_service=collection,
                )

                with (
                    patch("app.services.analysis_request_service.get_session", return_value=session),
                    self.assertLogs("app.services.analysis_request_service", level="WARNING"),
                ):
                    service.collect_keywords(9, "OAP", "IT/SaaS", "description")

                self.assertEqual(
                    [call.args[2] for call in repository.update_keyword_collection_status.call_args_list],
                    ["COLLECTING", "FAILED"],
                )

    def test_owner_gets_only_requested_naver_keywords_with_raw_values(self):
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=7)
        collected_at = datetime(2026, 8, 12, 13, 30, tzinfo=timezone.utc)
        rows = [
            (
                SimpleNamespace(
                    seed_type="PROBLEM",
                    pc_count_raw="< 10",
                    mobile_count_raw="150",
                    pc_count=5,
                    mobile_count=150,
                    total_count=155,
                    comp_idx="HIGH",
                    source="naver_searchad_keywordstool",
                    collected_at=collected_at,
                ),
                SimpleNamespace(keyword="스타트업마케팅", keyword_raw="스타트업 마케팅"),
            ),
            (
                SimpleNamespace(
                    seed_type="BRAND",
                    pc_count_raw="20",
                    mobile_count_raw="30",
                    pc_count=20,
                    mobile_count=30,
                    total_count=50,
                    comp_idx="LOW",
                    source="naver_searchad_keywordstool",
                    collected_at=collected_at,
                ),
                SimpleNamespace(keyword="OAP", keyword_raw="OAP"),
            ),
        ]
        with (
            patch("app.api.analysis_request.get_session") as get_session,
            patch(
                "app.api.analysis_request.AnalysisRequestService.get_owned_or_404",
                return_value=SimpleNamespace(keyword_collection_status="COMPLETED"),
            ),
            patch(
                "app.api.analysis_request.KeywordRepository.find_metrics_by_analysis_request",
                return_value=rows,
            ) as find_metrics,
        ):
            get_session.return_value.__enter__.return_value = SimpleNamespace()
            response = TestClient(app).get(
                "/api/v1/analysis-requests/123/naver-keywords"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "requestId": 123,
            "collectionStatus": "COMPLETED",
            "keywords": [
                {
                    "keyword": "스타트업마케팅",
                    "keywordRaw": "스타트업 마케팅",
                    "seedType": "PROBLEM",
                    "pcCountRaw": "< 10",
                    "mobileCountRaw": "150",
                    "pcCount": 5,
                    "mobileCount": 150,
                    "totalCount": 155,
                    "competition": "HIGH",
                    "source": "naver_searchad_keywordstool",
                    "collectedAt": "2026-08-12T13:30:00Z",
                },
                {
                    "keyword": "OAP",
                    "keywordRaw": "OAP",
                    "seedType": "BRAND",
                    "pcCountRaw": "20",
                    "mobileCountRaw": "30",
                    "pcCount": 20,
                    "mobileCount": 30,
                    "totalCount": 50,
                    "competition": "LOW",
                    "source": "naver_searchad_keywordstool",
                    "collectedAt": "2026-08-12T13:30:00Z",
                },
            ],
        })
        find_metrics.assert_called_once()
        self.assertEqual(find_metrics.call_args.args[1], 123)

    def test_owner_gets_empty_naver_keyword_list(self):
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=7)
        with (
            patch("app.api.analysis_request.get_session") as get_session,
            patch(
                "app.api.analysis_request.AnalysisRequestService.get_owned_or_404",
                return_value=SimpleNamespace(keyword_collection_status="COMPLETED"),
            ),
            patch(
                "app.api.analysis_request.KeywordRepository.find_metrics_by_analysis_request",
                return_value=[],
            ),
        ):
            get_session.return_value.__enter__.return_value = SimpleNamespace()
            response = TestClient(app).get(
                "/api/v1/analysis-requests/123/naver-keywords"
            )
        self.assertEqual(
            response.json(),
            {"requestId": 123, "collectionStatus": "COMPLETED", "keywords": []},
        )

    def test_naver_keywords_requires_authentication(self):
        response = TestClient(app).get(
            "/api/v1/analysis-requests/123/naver-keywords"
        )
        self.assertEqual(response.status_code, 401)

    def test_other_or_missing_analysis_request_is_404(self):
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=7)
        for request_id in (123, 999):
            with (
                self.subTest(request_id=request_id),
                patch("app.api.analysis_request.get_session") as get_session,
                patch(
                    "app.api.analysis_request.AnalysisRequestService.get_owned_or_404",
                    side_effect=HTTPException(status_code=404, detail="not found"),
                ),
                patch(
                    "app.api.analysis_request.KeywordRepository.find_metrics_by_analysis_request"
                ) as find_metrics,
            ):
                get_session.return_value.__enter__.return_value = SimpleNamespace()
                response = TestClient(app).get(
                    f"/api/v1/analysis-requests/{request_id}/naver-keywords"
                )
            self.assertEqual(response.status_code, 404)
            find_metrics.assert_not_called()


if __name__ == "__main__":
    unittest.main()
