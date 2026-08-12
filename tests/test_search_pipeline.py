import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.models.base import Base
from app.models.search_keyword import Keyword, KeywordMetric
from app.repositories.keyword_repository import KeywordRepository
from app.services.keyword_collection_service import (
    KeywordCollectionService,
    build_seeds,
    normalize_keyword,
    parse_count,
)
from app.services.naver_searchad_client import NaverSearchAdClient, NaverSearchAdError


class SearchPipelineTest(unittest.TestCase):
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
        from app.services.analysis_request_service import AnalysisRequestService

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

        with self.assertLogs("app.services.analysis_request_service", level="WARNING"):
            service.collect_keywords(
                saved.id,
                saved.service_name,
                saved.industry,
                saved.one_line_description,
            )

        self.assertEqual(saved.id, 7)
        collection.collect.assert_called_once_with(7, "OAP", "IT/SaaS", "설명")
        interview_repository.save_message.assert_called_once()


if __name__ == "__main__":
    unittest.main()
