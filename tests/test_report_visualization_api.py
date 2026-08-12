import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.auth import get_current_user
from app.main import app
from sqlalchemy.dialects import postgresql

from app.repositories.analysis_report_repository import AnalysisReportRepository
from app.schemas.analysis_report import AnalysisReportListResponse, AnalysisReportResponse
from app.services.analysis_report_service import AnalysisReportService


def response_payload():
    section = {
        "title": "Title",
        "summary": "Summary",
        "insights": [],
        "recommendations": [],
    }
    return AnalysisReportResponse(
        serviceSummary=section,
        marketAnalysis=section,
        competitorAnalysis=section,
        targetCustomerAnalysis=section,
        marketingStrategy=section,
        platformRecommendation=section,
        reportMeta={
            "schemaVersion": "3.0",
            "requestId": 10,
            "generatedAt": None,
            "dataAsOf": None,
            "overallConfidence": None,
            "evidenceCount": 0,
            "analysisLocale": "ko-KR",
        },
        headlineMetrics=[],
    )


def list_response_payload(page=0, size=20, total=2):
    return AnalysisReportListResponse(
        items=[
            {
                "requestId": 12,
                "serviceName": "Newest",
                "oneLineDescription": "Newest report",
                "industry": "SaaS",
                "status": "COMPLETED",
                "createdAt": "2026-08-04T12:00:00Z",
            },
            {
                "requestId": 11,
                "serviceName": "Older",
                "oneLineDescription": "Older report",
                "industry": "Commerce",
                "status": "COMPLETED",
                "createdAt": "2026-08-03T12:00:00Z",
            },
        ][:size],
        page=page,
        size=size,
        totalElements=total,
        totalPages=(total + size - 1) // size,
    )


class ReportVisualizationApiTest(unittest.TestCase):
    def tearDown(self):
        app.dependency_overrides.clear()

    def test_unauthenticated_report_is_401(self):
        response = TestClient(app).get("/api/v1/analysis-requests/10/report")
        self.assertEqual(response.status_code, 401)

    def test_other_user_report_is_404(self):
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=7)
        with (
            patch("app.api.analysis.get_session") as get_session,
            patch(
                "app.api.analysis.AnalysisRequestService.get_owned_or_404",
                side_effect=HTTPException(status_code=404, detail="not found"),
            ),
        ):
            get_session.return_value.__enter__.return_value = SimpleNamespace()
            response = TestClient(app).get("/api/v1/analysis-requests/10/report")
        self.assertEqual(response.status_code, 404)

    def test_owner_report_returns_legacy_and_new_contract_without_tokens(self):
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=7)
        with (
            patch("app.api.analysis.get_session") as get_session,
            patch("app.api.analysis.AnalysisRequestService.get_owned_or_404"),
            patch(
                "app.api.analysis.AnalysisReportService.get_report",
                return_value=response_payload(),
            ),
        ):
            get_session.return_value.__enter__.return_value = SimpleNamespace()
            response = TestClient(app).get("/api/v1/analysis-requests/10/report")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        for key in (
            "serviceSummary",
            "marketAnalysis",
            "competitorAnalysis",
            "targetCustomerAnalysis",
            "marketingStrategy",
            "platformRecommendation",
            "reportMeta",
            "headlineMetrics",
        ):
            self.assertIn(key, payload)
        self.assertIn("opportunityMatrix", payload["marketAnalysis"])
        self.assertIn("demandTrend", payload["marketAnalysis"])
        self.assertIn("competitors", payload["competitorAnalysis"])
        self.assertIn("currentKpiValue", payload["marketingStrategy"])
        self.assertNotIn("token", response.text.lower())

    def test_unauthenticated_report_list_is_401(self):
        response = TestClient(app).get("/api/v1/reports")
        self.assertEqual(response.status_code, 401)

    def test_unauthenticated_report_delete_is_401(self):
        response = TestClient(app).delete("/api/v1/reports/10")
        self.assertEqual(response.status_code, 401)

    def test_owner_report_delete_is_204_without_body(self):
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=7)
        with patch(
            "app.api.analysis.AnalysisReportService.delete_report"
        ) as delete_report:
            response = TestClient(app).delete("/api/v1/reports/10")

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")
        delete_report.assert_called_once_with(10, 7)

    def test_missing_other_user_or_request_without_report_is_404(self):
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=7)
        for request_id in (10, 999, 11):
            with self.subTest(request_id=request_id), patch(
                "app.api.analysis.AnalysisReportService.delete_report",
                side_effect=HTTPException(status_code=404, detail="analysis report not found"),
            ):
                response = TestClient(app).delete(f"/api/v1/reports/{request_id}")
            self.assertEqual(response.status_code, 404)

    def test_report_list_returns_items_and_pagination(self):
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=7)
        with patch(
            "app.api.analysis.AnalysisReportService.get_reports",
            return_value=list_response_payload(),
        ) as get_reports:
            response = TestClient(app).get("/api/v1/reports?page=0&size=20")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["requestId"] for item in response.json()["items"]], [12, 11])
        self.assertEqual(
            {key: response.json()[key] for key in ("page", "size", "totalElements", "totalPages")},
            {"page": 0, "size": 20, "totalElements": 2, "totalPages": 1},
        )
        get_reports.assert_called_once_with(7, 0, 20)
        for forbidden in ("userId", "reportId", "retrieval", "serviceSummary"):
            self.assertNotIn(forbidden, response.text)

    def test_report_list_empty_page(self):
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=7)
        empty = AnalysisReportListResponse(
            items=[], page=0, size=20, totalElements=0, totalPages=0
        )
        with patch(
            "app.api.analysis.AnalysisReportService.get_reports",
            return_value=empty,
        ):
            response = TestClient(app).get("/api/v1/reports")
        self.assertEqual(response.json(), empty.model_dump(mode="json"))

    def test_report_list_next_page_metadata(self):
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=7)
        payload = AnalysisReportListResponse(
            items=list_response_payload().items[1:],
            page=1,
            size=1,
            totalElements=2,
            totalPages=2,
        )
        with patch(
            "app.api.analysis.AnalysisReportService.get_reports",
            return_value=payload,
        ) as get_reports:
            response = TestClient(app).get("/api/v1/reports?page=1&size=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["requestId"], 11)
        self.assertEqual(response.json()["totalPages"], 2)
        get_reports.assert_called_once_with(7, 1, 1)

    def test_report_list_rejects_invalid_pagination(self):
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=7)
        for query in ("page=-1&size=20", "page=0&size=0", "page=0&size=101"):
            with self.subTest(query=query):
                response = TestClient(app).get(f"/api/v1/reports?{query}")
                self.assertEqual(response.status_code, 422)


class ReportListServiceTest(unittest.TestCase):
    def test_service_maps_rows_and_calculates_total_pages(self):
        rows = [
            SimpleNamespace(
                id=12,
                service_name="A",
                one_line_description="Description",
                industry="SaaS",
                status="COMPLETED",
                created_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
            )
        ]

        class Repository:
            def find_completed_reports(self, session, user_id, page, size):
                self.args = (session, user_id, page, size)
                return rows, 21

        repository = Repository()
        session = SimpleNamespace(
            __enter__=lambda self: self,
            __exit__=lambda self, *args: False,
        )

        class SessionContext:
            def __enter__(self):
                return session

            def __exit__(self, *args):
                return False

        with patch(
            "app.services.analysis_report_service.get_session",
            return_value=SessionContext(),
        ):
            response = AnalysisReportService(repository=repository).get_reports(7, 1, 20)

        self.assertEqual(response.items[0].requestId, 12)
        self.assertEqual(response.totalElements, 21)
        self.assertEqual(response.totalPages, 2)
        self.assertEqual(repository.args[1:], (7, 1, 20))


class ReportDeleteServiceTest(unittest.TestCase):
    class Session:
        def __init__(self):
            self.commits = 0
            self.rollbacks = 0

        def commit(self):
            self.commits += 1

        def rollback(self):
            self.rollbacks += 1

    class SessionContext:
        def __init__(self, session):
            self.session = session

        def __enter__(self):
            return self.session

        def __exit__(self, *args):
            return False

    def test_delete_commits_parent_request_in_same_session(self):
        session = self.Session()

        class Repository:
            def delete_owned_report_request(self, received_session, request_id, user_id):
                self.args = (received_session, request_id, user_id)
                return True

        repository = Repository()
        with patch(
            "app.services.analysis_report_service.get_session",
            return_value=self.SessionContext(session),
        ):
            AnalysisReportService(repository=repository).delete_report(10, 7)

        self.assertEqual(repository.args, (session, 10, 7))
        self.assertEqual(session.commits, 1)
        self.assertEqual(session.rollbacks, 0)

    def test_delete_not_found_rolls_back_and_uses_same_404(self):
        session = self.Session()

        class Repository:
            def delete_owned_report_request(self, session, request_id, user_id):
                return False

        with patch(
            "app.services.analysis_report_service.get_session",
            return_value=self.SessionContext(session),
        ), self.assertRaises(HTTPException) as raised:
            AnalysisReportService(repository=Repository()).delete_report(10, 7)

        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(session.commits, 0)
        self.assertEqual(session.rollbacks, 1)


class ReportListRepositoryTest(unittest.TestCase):
    def test_delete_query_checks_owner_and_report_then_deletes_parent_request(self):
        analysis_request = SimpleNamespace(id=10)

        class Session:
            def scalar(self, statement):
                self.statement = statement
                return analysis_request

            def delete(self, target):
                self.deleted = target

        session = Session()
        deleted = AnalysisReportRepository().delete_owned_report_request(
            session,
            request_id=10,
            user_id=7,
        )

        sql = str(
            session.statement.compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        )
        self.assertTrue(deleted)
        self.assertIs(session.deleted, analysis_request)
        self.assertIn("JOIN analysis_reports", sql)
        self.assertIn("analysis_requests.id = 10", sql)
        self.assertIn("analysis_requests.user_id = 7", sql)

    def test_delete_query_does_not_delete_when_owner_report_match_is_missing(self):
        class Session:
            def scalar(self, statement):
                return None

            def delete(self, target):
                raise AssertionError("must not delete")

        self.assertFalse(
            AnalysisReportRepository().delete_owned_report_request(
                Session(),
                request_id=10,
                user_id=7,
            )
        )

    def test_query_has_ownership_report_status_order_pagination_and_count(self):
        class Result:
            def all(self):
                return []

        class Session:
            def __init__(self):
                self.item_statements = []
                self.count_statements = []

            def execute(self, statement):
                self.item_statements.append(statement)
                return Result()

            def scalar(self, statement):
                self.count_statements.append(statement)
                return 0

        session = Session()
        items, total = AnalysisReportRepository().find_completed_reports(
            session, user_id=7, page=1, size=20
        )
        self.assertEqual((items, total), ([], 0))
        self.assertEqual(len(session.item_statements), 1)
        self.assertEqual(len(session.count_statements), 1)

        sql = str(
            session.item_statements[0].compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        )
        count_sql = str(
            session.count_statements[0].compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        )
        self.assertIn("JOIN analysis_reports", sql)
        self.assertIn("analysis_requests.user_id = 7", sql)
        self.assertIn("analysis_requests.status = 'COMPLETED'", sql)
        self.assertIn(
            "ORDER BY analysis_requests.created_at DESC, analysis_requests.id DESC",
            sql,
        )
        self.assertIn("LIMIT 20 OFFSET 20", sql)
        self.assertNotIn("service_summary", sql)
        self.assertIn("JOIN analysis_reports", count_sql)
        self.assertIn("analysis_requests.user_id = 7", count_sql)
        self.assertIn("analysis_requests.status = 'COMPLETED'", count_sql)


if __name__ == "__main__":
    unittest.main()
