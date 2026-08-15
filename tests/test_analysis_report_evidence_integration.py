import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.ai.report_ai import (
    build_report_evidence_context,
    build_report_retrieval_query,
    generate_analysis_report_with_citations,
)
from app.ai.report_retriever import retrieve_report_evidences
from app.models.retrieval_audit import RetrievalEvidence
from app.schemas.analysis_report import AnalysisStartResponse
from app.services.analysis_report_service import AnalysisReportService
from app.services.report_citation_service import ReportCitationService
from app.services.retrieval_audit_service import RetrievalAuditService


REPORT_PAYLOAD = {
    "service_summary": {"title": "summary"},
    "market_analysis": {"title": "market"},
    "competitor_analysis": {"title": "competitor"},
    "target_customer_analysis": {"title": "customer"},
    "marketing_strategy": {"title": "marketing"},
    "platform_recommendation": {"title": "platform"},
}


class FakeSession:
    def __init__(self):
        self.rollback_count = 0
        self.commit_count = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def rollback(self):
        self.rollback_count += 1

    def commit(self):
        self.commit_count += 1

    def refresh(self, instance):
        return None


class FakeRepository:
    def __init__(self, request):
        self.request = request
        self.saved_report = None

    def find_analysis_request(self, session, request_id):
        return self.request

    def find_report(self, session, request_id):
        return None

    def start_analysis(self, session, analysis_request, analysis_report):
        analysis_report.id = 901
        self.saved_report = analysis_report
        return analysis_request, analysis_report


class FakeRepositoryWithReport(FakeRepository):
    def find_report(self, session, request_id):
        return SimpleNamespace(id=901, analysis_request_id=request_id)


class FakeInterviewRepository:
    def __init__(self, messages):
        self.messages = messages

    def find_messages(self, session, request_id):
        return self.messages


class FakeKeywordRepository:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.request_ids = []

    def find_metrics_by_analysis_request(self, session, analysis_request_id):
        self.request_ids.append(analysis_request_id)
        return self.rows


class FakeRetrievalAuditService:
    def __init__(self, *, fail_record=False, fail_attach=False):
        self.fail_record = fail_record
        self.fail_attach = fail_attach
        self.record_calls = []
        self.attach_calls = []

    def record_retrieval(self, *args, **kwargs):
        if self.fail_record:
            raise RuntimeError("audit failed")
        self.record_calls.append((args, kwargs))
        evidences = args[3]
        persisted_evidences = [
            SimpleNamespace(id=1000 + evidence["rank"], rank=evidence["rank"])
            for evidence in evidences
        ]
        return SimpleNamespace(id=501, evidences=persisted_evidences)

    def attach_report(self, *args, **kwargs):
        if self.fail_attach:
            raise RuntimeError("attach failed")
        self.attach_calls.append((args, kwargs))
        return SimpleNamespace(id=args[1], analysis_report_id=args[2])


class FakeReportCitationService:
    def __init__(self, *, fail_save=False):
        self.fail_save = fail_save
        self.save_calls = []

    def save_report_citations(self, *args, **kwargs):
        if self.fail_save:
            raise RuntimeError("citation save failed")
        self.save_calls.append((args, kwargs))

    def validate_section_evidence_ids(
        self,
        session,
        *,
        retrieval_run_id,
        section_evidence_ids,
    ):
        return section_evidence_ids

    def sanitize_report_evidence_ids(
        self,
        report_payload,
        valid_section_evidence_ids,
    ):
        return report_payload

    def get_citations_by_analysis_request_id(self, session, analysis_request_id):
        return {key: [] for key in REPORT_PAYLOAD}


class FakeReportCitationLookupService(FakeReportCitationService):
    def get_citations_by_analysis_request_id(self, session, analysis_request_id):
        citations = {key: [] for key in REPORT_PAYLOAD}
        citations["market_analysis"] = [
            {
                "evidence_id": 1001,
                "content": "Market evidence",
                "source": "document_id=11, chunk_index=2",
                "metadata": {"category": "market"},
            }
        ]
        return citations


def make_request():
    return SimpleNamespace(
        id=101,
        service_name="OAP",
        one_line_description="AI report service",
        industry="knowledge platform",
        main_question="Find a launch strategy",
        status="INTERVIEWING",
        interview_completed=False,
    )


def make_messages():
    return [
        SimpleNamespace(
            role="USER",
            content="Main features are report generation and evidence search.",
            message_order=1,
        ),
        SimpleNamespace(
            role="AI",
            content="What is your target customer?",
            message_order=2,
        ),
        SimpleNamespace(
            role="USER",
            content="Target customers are early startup teams.",
            message_order=3,
        ),
    ]


class AnalysisReportEvidenceIntegrationTest(unittest.TestCase):
    def build_service(
        self,
        request,
        messages,
        audit_service,
        citation_service=None,
        keyword_repository=None,
    ):
        return AnalysisReportService(
            repository=FakeRepository(request),
            interview_message_repository=FakeInterviewRepository(messages),
            retrieval_audit_service=audit_service,
            report_citation_service=citation_service or FakeReportCitationService(),
            keyword_repository=keyword_repository or FakeKeywordRepository(),
        )

    def test_start_analysis_records_evidence_and_attaches_saved_report(self):
        session = FakeSession()
        request = make_request()
        messages = make_messages()
        audit_service = FakeRetrievalAuditService()
        citation_service = FakeReportCitationService()
        service = self.build_service(request, messages, audit_service, citation_service)
        evidences = [
            {
                "rank": 1,
                "content": "Use domestic market evidence.",
                "document_id": 11,
                "chunk_index": 2,
                "metadata": {"title": "Market guide", "category": "market"},
                "scores": {"similarity": 0.91, "hybrid": 0.21},
            }
        ]

        with (
            patch("app.services.analysis_report_service.get_session", return_value=session),
            patch(
                "app.services.analysis_report_service.retrieve_report_evidences",
                return_value=evidences,
            ) as retrieve_mock,
            patch(
                "app.services.analysis_report_service.generate_analysis_report_with_citations",
                return_value=(REPORT_PAYLOAD, {"market_analysis": [1001]}),
            ) as generate_mock,
        ):
            response = service.start_analysis(101)

        self.assertIsInstance(response, AnalysisStartResponse)
        self.assertEqual(response.model_dump(), {"requestId": 101, "status": "COMPLETED"})
        retrieve_mock.assert_called_once()
        self.assertEqual(retrieve_mock.call_args.kwargs["top_k"], 4)
        self.assertEqual(len(audit_service.record_calls), 1)
        record_args, record_kwargs = audit_service.record_calls[0]
        self.assertEqual(record_args[1], 101)
        self.assertIn("service_name: OAP", record_args[2])
        self.assertEqual(record_args[3][0]["rank"], 1)
        self.assertIn("Evidence Type: KNOWLEDGE", record_args[3][0]["content"])
        self.assertEqual(record_kwargs["retrieval_method"], "vector")
        self.assertEqual(record_kwargs["top_k"], 1)
        self.assertEqual(len(audit_service.attach_calls), 1)
        attach_args, _ = audit_service.attach_calls[0]
        self.assertEqual(attach_args[1], 501)
        self.assertEqual(attach_args[2], 901)
        self.assertIn("[Evidence ID: 1001]", generate_mock.call_args.kwargs["evidence_context"])
        self.assertIn("Use domestic market evidence.", generate_mock.call_args.kwargs["evidence_context"])
        self.assertEqual(len(citation_service.save_calls), 1)
        _, citation_kwargs = citation_service.save_calls[0]
        self.assertEqual(citation_kwargs["analysis_report_id"], 901)
        self.assertEqual(citation_kwargs["retrieval_run_id"], 501)
        self.assertEqual(citation_kwargs["section_evidence_ids"], {"market_analysis": [1001]})

    def test_search_metric_keeps_request_ownership_fields_and_audit_evidence_id(self):
        session = FakeSession()
        metric = SimpleNamespace(
            id=71,
            seed_type="PROBLEM",
            pc_count=5,
            pc_count_raw="< 10",
            mobile_count=20,
            mobile_count_raw="20",
            total_count=25,
            source="naver_searchad_keywordstool",
            collected_at=__import__("datetime").datetime(
                2026, 8, 12, 3, 0, tzinfo=__import__("datetime").timezone.utc
            ),
        )
        keyword_repository = FakeKeywordRepository(
            [(metric, SimpleNamespace(keyword="스타트업마케팅"))]
        )
        audit_service = FakeRetrievalAuditService()
        citation_service = FakeReportCitationService()
        service = self.build_service(
            make_request(),
            make_messages(),
            audit_service,
            citation_service,
            keyword_repository,
        )
        knowledge = [{
            "rank": 1,
            "content": "Static market guide",
            "document_id": 11,
            "chunk_index": 2,
            "metadata": {},
            "scores": {"similarity": 0.9},
        }]

        with (
            patch("app.services.analysis_report_service.get_session", return_value=session),
            patch(
                "app.services.analysis_report_service.retrieve_report_evidences",
                return_value=knowledge,
            ),
            patch(
                "app.services.analysis_report_service.generate_analysis_report_with_citations",
                return_value=(REPORT_PAYLOAD, {"market_analysis": [1001]}),
            ) as generate_mock,
        ):
            service.start_analysis(101)

        self.assertEqual(keyword_repository.request_ids, [101])
        recorded = audit_service.record_calls[0][0][3]
        self.assertEqual(recorded[0]["metadata"]["evidence_type"], "SEARCH_METRIC")
        self.assertEqual(recorded[1]["metadata"]["evidence_type"], "KNOWLEDGE")
        context = generate_mock.call_args.kwargs["evidence_context"]
        self.assertIn("[Evidence ID: 1001]", context)
        self.assertIn("Evidence Type: SEARCH_METRIC", context)
        self.assertIn("검색어: 스타트업마케팅", context)
        self.assertIn("seed: PROBLEM", context)
        self.assertIn("PC 검색량: 5", context)
        self.assertIn("PC raw: < 10", context)
        self.assertIn("모바일 검색량: 20", context)
        self.assertIn("모바일 raw: 20", context)
        self.assertIn("총 검색량: 25", context)
        self.assertIn("출처: naver_searchad_keywordstool", context)
        self.assertIn("수집 시각: 2026-08-12T03:00:00+00:00", context)
        self.assertIn("[Evidence ID: 1002]", context)
        self.assertIn("Evidence Type: KNOWLEDGE", context)
        saved_ids = citation_service.save_calls[0][1]["section_evidence_ids"]
        self.assertEqual(saved_ids["market_analysis"], [1001])

    def test_mixed_search_metric_and_knowledge_evidences_keep_document_snapshots(self):
        repository = MagicMock()
        service = RetrievalAuditService(repository=repository)
        evidences = [
            {
                "content": "Evidence Type: SEARCH_METRIC",
                "metadata": {"evidence_type": "SEARCH_METRIC"},
                "rank": 1,
            },
            {
                "content": "Evidence Type: KNOWLEDGE",
                "document_id": 11,
                "chunk_index": 2,
                "metadata": {"evidence_type": "KNOWLEDGE"},
                "rank": 2,
            },
        ]

        service.record_retrieval(
            SimpleNamespace(),
            101,
            "query",
            evidences,
            top_k=2,
        )

        payload = repository.create_run_with_evidences.call_args.args[1]
        self.assertIsNone(payload["evidences"][0]["document_id_snapshot"])
        self.assertIsNone(payload["evidences"][0]["chunk_index_snapshot"])
        self.assertEqual(payload["evidences"][1]["document_id_snapshot"], 11)
        self.assertEqual(payload["evidences"][1]["chunk_index_snapshot"], 2)
        self.assertTrue(RetrievalEvidence.document_id_snapshot.nullable)
        self.assertTrue(RetrievalEvidence.chunk_index_snapshot.nullable)

    def test_start_analysis_continues_when_no_evidence_is_found(self):
        session = FakeSession()
        request = make_request()
        audit_service = FakeRetrievalAuditService()
        service = self.build_service(request, make_messages(), audit_service)

        with (
            patch("app.services.analysis_report_service.get_session", return_value=session),
            patch(
                "app.services.analysis_report_service.retrieve_report_evidences",
                return_value=[],
            ),
            patch(
                "app.services.analysis_report_service.generate_analysis_report_with_citations",
                return_value=(REPORT_PAYLOAD, {}),
            ) as generate_mock,
        ):
            response = service.start_analysis(101)

        self.assertEqual(response.model_dump(), {"requestId": 101, "status": "COMPLETED"})
        self.assertEqual(audit_service.record_calls, [])
        self.assertEqual(generate_mock.call_args.kwargs["evidence_context"], "")
        self.assertEqual(audit_service.attach_calls, [])

    def test_audit_exception_rolls_back_and_does_not_complete_report(self):
        session = FakeSession()
        request = make_request()
        audit_service = FakeRetrievalAuditService(fail_record=True)
        service = self.build_service(request, make_messages(), audit_service)

        with (
            patch("app.services.analysis_report_service.get_session", return_value=session),
            patch(
                "app.services.analysis_report_service.retrieve_report_evidences",
                return_value=[{"rank": 1, "content": "Evidence"}],
            ),
            patch(
                "app.services.analysis_report_service.generate_analysis_report_with_citations",
                return_value=(REPORT_PAYLOAD, {}),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "audit failed"):
                service.start_analysis(101)

        self.assertEqual(session.rollback_count, 1)
        self.assertEqual(audit_service.attach_calls, [])
        self.assertEqual(request.status, "INTERVIEWING")

    def test_attach_exception_rolls_back_and_does_not_complete_report(self):
        session = FakeSession()
        request = make_request()
        audit_service = FakeRetrievalAuditService(fail_attach=True)
        service = self.build_service(request, make_messages(), audit_service)

        with (
            patch("app.services.analysis_report_service.get_session", return_value=session),
            patch(
                "app.services.analysis_report_service.retrieve_report_evidences",
                return_value=[{"rank": 1, "content": "Evidence"}],
            ),
            patch(
                "app.services.analysis_report_service.generate_analysis_report_with_citations",
                return_value=(REPORT_PAYLOAD, {}),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "attach failed"):
                service.start_analysis(101)

        self.assertEqual(session.rollback_count, 1)
        self.assertEqual(request.status, "INTERVIEWING")

    def test_get_report_citations_returns_section_keyed_response(self):
        session = FakeSession()
        service = AnalysisReportService(
            repository=FakeRepositoryWithReport(make_request()),
            interview_message_repository=FakeInterviewRepository(make_messages()),
            retrieval_audit_service=FakeRetrievalAuditService(),
            report_citation_service=FakeReportCitationLookupService(),
        )

        with patch("app.services.analysis_report_service.get_session", return_value=session):
            response = service.get_report_citations(101)

        payload = response.model_dump()
        self.assertEqual(payload["market_analysis"][0]["evidence_id"], 1001)
        self.assertEqual(payload["market_analysis"][0]["content"], "Market evidence")
        self.assertEqual(payload["service_summary"], [])


class ReportEvidenceHelperTest(unittest.TestCase):
    def test_retrieval_query_uses_actual_analysis_request_and_user_answers(self):
        query = build_report_retrieval_query(make_request(), make_messages())

        self.assertIn("service_name: OAP", query)
        self.assertIn("service_description: AI report service", query)
        self.assertIn("industry_or_category: knowledge platform", query)
        self.assertIn("analysis_purpose: Find a launch strategy", query)
        self.assertIn("report generation and evidence search", query)
        self.assertIn("early startup teams", query)
        self.assertNotIn("What is your target customer?", query)

    def test_evidence_context_keeps_rank_content_source_and_scores(self):
        context = build_report_evidence_context(
            [
                {
                    "rank": 2,
                    "content": "Domestic competitors should be compared.",
                    "document_id": 31,
                    "chunk_index": 7,
                    "metadata": {
                        "title": "Competitor playbook",
                        "domain": "report",
                        "category": "competitor",
                        "ignored_internal": "not surfaced",
                    },
                    "scores": {"similarity": 0.81234, "text": None},
                }
            ]
        )

        self.assertIn("[Evidence 2]", context)
        self.assertIn("내용: Domestic competitors should be compared.", context)
        self.assertIn("document_id=31", context)
        self.assertIn("chunk_index=7", context)
        self.assertIn("title=Competitor playbook", context)
        self.assertIn("category=competitor", context)
        self.assertIn("similarity=0.8123", context)
        self.assertNotIn("ignored_internal", context)

    def test_evidence_context_is_empty_for_empty_results(self):
        self.assertEqual(build_report_evidence_context([]), "")

    def test_evidence_context_prefers_persisted_retrieval_evidence_id(self):
        context = build_report_evidence_context(
            [
                {
                    "rank": 1,
                    "retrieval_evidence_id": 501,
                    "content": "Evidence with persisted id.",
                    "document_id": 9,
                    "chunk_index": 3,
                    "metadata": {},
                    "scores": {},
                }
            ]
        )

        self.assertIn("[Evidence ID: 501]", context)
        self.assertNotIn("[Evidence 1]", context)

    def test_generate_report_extracts_and_strips_section_evidence_ids(self):
        ai_payload = {
            **REPORT_PAYLOAD,
            "market_analysis": {
                **REPORT_PAYLOAD["market_analysis"],
                "evidence_ids": [501, 502, 501, "bad"],
            },
            "target_customer_analysis": {
                **REPORT_PAYLOAD["target_customer_analysis"],
                "evidence_ids": [],
            },
        }

        with patch(
            "app.ai.report_ai._request_analysis_report",
            return_value=__import__("json").dumps(ai_payload),
        ):
            report, citations = generate_analysis_report_with_citations(make_request())

        self.assertNotIn("evidence_ids", report["market_analysis"])
        self.assertEqual(citations["market_analysis"], [501, 502])
        self.assertEqual(citations["target_customer_analysis"], [])


class ReportRetrieverTest(unittest.TestCase):
    def test_retrieve_report_evidences_passes_requested_top_k_to_service(self):
        fake_session = SimpleNamespace(close=lambda: None)

        class FakeRetrievalService:
            def retrieve(self, session, query, top_k):
                self.session = session
                self.query = query
                self.top_k = top_k
                return [
                    {
                        "content": "Evidence body",
                        "document_id": 1,
                        "chunk_index": 0,
                        "metadata": {"category": "market"},
                        "similarity_score": 0.7,
                    }
                ]

        fake_service = FakeRetrievalService()

        with (
            patch("app.ai.report_retriever.get_session", return_value=fake_session),
            patch(
                "app.ai.report_retriever.KnowledgeRetrievalService",
                return_value=fake_service,
            ),
        ):
            evidences = retrieve_report_evidences("search query", top_k=4)

        self.assertEqual(fake_service.top_k, 4)
        self.assertEqual(evidences[0]["rank"], 1)
        self.assertEqual(evidences[0]["scores"]["similarity"], 0.7)


class FakeCitationRepository:
    def __init__(self, evidences):
        self.evidences = evidences
        self.saved = None

    def find_evidences_by_ids(self, session, evidence_ids):
        return [
            evidence
            for evidence in self.evidences
            if evidence.id in evidence_ids
        ]

    def replace_report_citations(self, session, analysis_report_id, section_evidence_ids):
        self.saved = (analysis_report_id, section_evidence_ids)
        return []


class ReportCitationServiceTest(unittest.TestCase):
    def test_validate_section_evidence_ids_filters_invalid_foreign_and_duplicate_ids(self):
        repository = FakeCitationRepository(
            [
                SimpleNamespace(id=501, retrieval_run_id=10),
                SimpleNamespace(id=502, retrieval_run_id=10),
                SimpleNamespace(id=601, retrieval_run_id=99),
            ]
        )
        service = ReportCitationService(repository=repository)

        result = service.validate_section_evidence_ids(
            SimpleNamespace(),
            retrieval_run_id=10,
            section_evidence_ids={
                "market_analysis": [501, 501, 999, 601, "bad", 502],
                "target_customer_analysis": [],
                "not_a_section": [501],
            },
        )

        self.assertEqual(result["market_analysis"], [501, 502])
        self.assertEqual(result["target_customer_analysis"], [])
        self.assertNotIn("not_a_section", result)

    def test_citation_response_normalizes_metadata_and_deduplicates_source(self):
        evidence_one = SimpleNamespace(
            id=501,
            content_snapshot="First chunk",
            document_id_snapshot=11,
            chunk_index_snapshot=1,
            metadata_snapshot={
                "title": "Verified report",
                "url": "https://example.com/report/",
                "publisher": "Example Publisher",
                "published_at": "2026-07-01",
            },
        )
        evidence_two = SimpleNamespace(
            id=502,
            content_snapshot="Second chunk",
            document_id_snapshot=11,
            chunk_index_snapshot=2,
            metadata_snapshot={
                "title": "Verified report",
                "url": "https://example.com/report",
                "publisher": "Example Publisher",
                "published_at": "2026-07-01",
            },
        )
        repository = MagicMock()
        repository.find_by_analysis_request_id.return_value = [
            SimpleNamespace(
                section_key="market_analysis",
                retrieval_evidence_id=501,
                retrieval_evidence=evidence_one,
            ),
            SimpleNamespace(
                section_key="market_analysis",
                retrieval_evidence_id=502,
                retrieval_evidence=evidence_two,
            ),
        ]

        result = ReportCitationService(
            repository=repository
        ).get_citations_by_analysis_request_id(SimpleNamespace(), 101)

        self.assertEqual(len(result["market_analysis"]), 1)
        reference = result["market_analysis"][0]
        self.assertEqual(reference["evidence_id"], 501)
        self.assertEqual(reference["metadata"]["title"], "Verified report")
        self.assertEqual(reference["metadata"]["publishedAt"], "2026-07-01")

    def test_citation_response_keeps_distinct_evidence_without_source_metadata(self):
        repository = MagicMock()
        repository.find_by_analysis_request_id.return_value = [
            SimpleNamespace(
                section_key="service_summary",
                retrieval_evidence_id=evidence_id,
                retrieval_evidence=SimpleNamespace(
                    content_snapshot=f"Evidence {evidence_id}",
                    document_id_snapshot=None,
                    chunk_index_snapshot=None,
                    metadata_snapshot={},
                ),
            )
            for evidence_id in (501, 502)
        ]

        result = ReportCitationService(
            repository=repository
        ).get_citations_by_analysis_request_id(SimpleNamespace(), 101)

        self.assertEqual(len(result["service_summary"]), 2)
        self.assertEqual(result["market_analysis"], [])


if __name__ == "__main__":
    unittest.main()
