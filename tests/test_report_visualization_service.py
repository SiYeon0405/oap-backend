import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from app.ai.report_ai import generate_analysis_report_with_citations
from app.services.analysis_report_service import AnalysisReportService
from app.services.report_citation_service import ReportCitationService


SECTION_KEYS = (
    "service_summary",
    "market_analysis",
    "competitor_analysis",
    "target_customer_analysis",
    "marketing_strategy",
    "platform_recommendation",
)


def text_section(title):
    return {
        "title": title,
        "summary": f"{title} summary",
        "insights": [f"{title} insight"],
        "recommendations": [f"{title} recommendation"],
    }


class FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class ReportRepository:
    def __init__(self, report):
        self.report = report

    def find_analysis_request(self, session, request_id):
        return SimpleNamespace(id=request_id)

    def find_report(self, session, request_id):
        return self.report


class CitationLookupService(ReportCitationService):
    def __init__(self, citations):
        self.citations = citations

    def get_citations_by_analysis_request_id(self, session, analysis_request_id):
        return self.citations


def report_record(*, current=False):
    service = text_section("service")
    if current:
        service["_schemaVersion"] = "3.0"
        service["_headlineMetrics"] = [
            {
                "key": "market_attractiveness",
                "label": "Market",
                "value": 60,
                "unit": "score",
                "direction": "higher_is_better",
                "valueType": "estimated",
                "calculation": "정성 근거를 기반으로 한 AI 추정",
                "evidenceIds": [101, 999],
            }
        ]
    return SimpleNamespace(
        service_summary=service,
        market_analysis=text_section("market"),
        competitor_analysis=text_section("competitor"),
        target_customer_analysis=text_section("target"),
        marketing_strategy=text_section("marketing"),
        platform_recommendation=text_section("platform"),
        created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )


class ReportVisualizationServiceTest(unittest.TestCase):
    def get_response(self, report, citations=None):
        citation_payload = {key: [] for key in SECTION_KEYS}
        if citations:
            citation_payload.update(citations)
        service = AnalysisReportService(
            repository=ReportRepository(report),
            report_citation_service=CitationLookupService(citation_payload),
        )
        with patch(
            "app.services.analysis_report_service.get_session",
            return_value=FakeSession(),
        ):
            return service.get_report(77)

    def test_legacy_report_preserves_text_and_adds_empty_contract(self):
        response = self.get_response(report_record())
        payload = response.model_dump(mode="json")
        self.assertEqual(payload["reportMeta"]["schemaVersion"], "2.1-legacy")
        self.assertEqual(payload["serviceSummary"]["title"], "service")
        self.assertEqual(payload["headlineMetrics"], [])
        self.assertEqual(payload["marketAnalysis"]["metrics"], [])
        self.assertEqual(payload["marketAnalysis"]["purchaseFactors"], [])
        self.assertEqual(payload["competitorAnalysis"]["messageCoverage"], [])
        self.assertEqual(payload["targetCustomerAnalysis"]["segments"], [])
        self.assertEqual(payload["marketingStrategy"]["executionPhases"], [])
        self.assertEqual(payload["platformRecommendation"]["rankedPlatforms"], [])
        self.assertIsNone(payload["marketingStrategy"]["currentKpiValue"])

    def test_current_report_uses_actual_request_time_and_citation_count(self):
        citation = {
            "evidence_id": 101,
            "content": "evidence",
            "source": "source",
            "metadata": {},
        }
        response = self.get_response(
            report_record(current=True),
            {"service_summary": [citation]},
        )
        payload = response.model_dump(mode="json")
        self.assertEqual(payload["reportMeta"]["schemaVersion"], "3.0")
        self.assertEqual(payload["reportMeta"]["requestId"], 77)
        self.assertEqual(payload["reportMeta"]["evidenceCount"], 1)
        self.assertEqual(len(payload["headlineMetrics"]), 4)
        coverage = payload["headlineMetrics"][-1]
        self.assertEqual(coverage["key"], "evidence_coverage")
        self.assertEqual(coverage["value"], 1)
        self.assertEqual(coverage["valueType"], "observed")

    def test_nested_invalid_evidence_is_removed_and_observed_value_is_null(self):
        payload = {
            "market_analysis": {
                "metrics": [
                    {
                        "value": 45,
                        "valueType": "observed",
                        "evidenceIds": [1, 1, 999],
                    }
                ]
            }
        }
        ReportCitationService().sanitize_report_evidence_ids(
            payload,
            {"market_analysis": []},
        )
        metric = payload["market_analysis"]["metrics"][0]
        self.assertEqual(metric["evidenceIds"], [])
        self.assertIsNone(metric["value"])

    def test_malformed_json_preserves_fallback_text_report(self):
        request = SimpleNamespace(
            service_name="Service",
            one_line_description="Description",
            industry="Industry",
            main_question="Question",
        )
        with patch("app.ai.report_ai._request_analysis_report", return_value="not-json"):
            report, citations = generate_analysis_report_with_citations(request)
        self.assertEqual(set(report), set(SECTION_KEYS))
        self.assertTrue(report["service_summary"]["title"])
        self.assertEqual(citations, {key: [] for key in SECTION_KEYS})

    def test_invalid_visual_score_drops_visuals_but_preserves_text(self):
        ai_payload = {key: text_section(key) for key in SECTION_KEYS}
        ai_payload["market_analysis"]["metrics"] = [
            {
                "key": "bad",
                "label": "Bad",
                "value": 101,
                "unit": "score",
                "direction": "neutral",
                "valueType": "observed",
            }
        ]
        request = SimpleNamespace(
            service_name="Service",
            one_line_description="Description",
            industry="Industry",
            main_question="Question",
        )
        with patch(
            "app.ai.report_ai._request_analysis_report",
            return_value=json.dumps(ai_payload),
        ):
            report, _ = generate_analysis_report_with_citations(request)
        self.assertEqual(report["market_analysis"]["title"], "market_analysis")
        self.assertEqual(report["market_analysis"]["metrics"], [])


if __name__ == "__main__":
    unittest.main()
