import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.auth import get_current_user
from app.main import app
from app.schemas.analysis_report import AnalysisReportResponse


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


class ReportVisualizationApiTest(unittest.TestCase):
    def tearDown(self):
        app.dependency_overrides.clear()

    def test_unauthenticated_report_is_401(self):
        response = TestClient(app).get("/api/v1/analysis-requests/10/report")
        self.assertEqual(response.status_code, 401)

    def test_other_user_report_is_404(self):
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=7)
        with patch(
            "app.api.analysis.AnalysisRequestService.get_owned_or_404",
            side_effect=HTTPException(status_code=404, detail="not found"),
        ):
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


if __name__ == "__main__":
    unittest.main()
