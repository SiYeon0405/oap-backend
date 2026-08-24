import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.models.admin import AdminAuditLog, AdminUser
from app.models.analytics import AnalyticsAdminAggregateState, AnalyticsAdminHourly, AnalyticsEvent
from app.models.user import User
from app.services.admin_read_service import AdminReadService, FAILURE_EVENTS, _user_status


class AdminReadP0Test(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{self.temp.name}/admin-read.db")
        event.listen(self.engine, "connect", lambda connection, _: connection.create_function("now", 0, lambda: datetime.now(timezone.utc).isoformat()))
        for table in (User.__table__, AnalyticsEvent.__table__, AnalyticsAdminHourly.__table__, AnalyticsAdminAggregateState.__table__, AdminUser.__table__, AdminAuditLog.__table__):
            table.create(self.engine, checkfirst=True)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.patcher = patch("app.services.admin_read_service.get_session", side_effect=self.sessions)
        self.patcher.start()
        self.start = datetime(2026, 8, 24, 0, tzinfo=timezone.utc)

    def tearDown(self):
        self.patcher.stop()
        self.engine.dispose()
        self.temp.cleanup()

    def add_user(self, status="ACTIVE"):
        with self.sessions() as session:
            user = User(email=f"{uuid4()}@example.com", password_hash="x", name="User", status=status)
            session.add(user)
            session.commit()
            return user.id

    def add_event(self, name, *, user_id=None, session_id="ses_abcdefgh1234", at=None, properties=None, result=None, page_name="analysis"):
        with self.sessions() as session:
            row = AnalyticsEvent(event_id=uuid4(), event_name=name, event_version=1, user_id=user_id, session_id=session_id, occurred_at=at or self.start, page_name=page_name, path_template="/analysis/{requestId}", result=result, properties=properties or {})
            session.add(row)
            session.commit()
            return row.event_id

    def test_status_mapping_and_existing_last_login_is_null(self):
        active = self.add_user("active")
        inactive = self.add_user("BLOCKED")
        with self.sessions() as session:
            self.assertIsNone(session.get(User, active).last_login_at)
        self.assertEqual(_user_status("ACTIVE"), "active")
        self.assertEqual(_user_status("active"), "active")
        self.assertEqual(_user_status("BLOCKED"), "inactive")
        self.assertEqual(_user_status(None), "inactive")
        service = AdminReadService()
        self.assertEqual(len(service.users(self.start, self.start + timedelta(days=1), None, "active", "createdAt:desc", 50, None)[0]), 1)
        self.assertEqual(len(service.users(self.start, self.start + timedelta(days=1), None, "inactive", "createdAt:desc", 50, None)[0]), 1)
        self.assertEqual(len(service.users(self.start, self.start + timedelta(days=1), None, "all", "createdAt:desc", 50, None)[0]), 2)

    def test_refresh_cutoff_kpis_and_login_failed_exclusion(self):
        user = self.add_user()
        self.add_event("analysis_created", user_id=user, session_id="ses_user123456", at=self.start + timedelta(minutes=1))
        self.add_event("report_viewed", session_id="ses_anon123456", at=self.start + timedelta(minutes=2))
        self.add_event("analysis_create_failed", user_id=user, session_id="ses_user123456", at=self.start + timedelta(minutes=3))
        self.add_event("login_failed", session_id="ses_anon123456", at=self.start + timedelta(minutes=4))
        cutoff = self.start + timedelta(hours=1)
        service = AdminReadService()
        self.assertEqual(service.refresh_aggregates(cutoff), cutoff)
        metrics, through = service.dashboard(self.start, cutoff)
        self.assertEqual(through, cutoff)
        self.assertEqual(metrics, {"activeUsers": 1, "anonymousSessions": 1, "totalSessions": 2, "totalEvents": 4, "analysesCreated": 1, "reportsViewed": 1, "failures": 1})
        self.assertEqual(FAILURE_EVENTS, {"analysis_create_failed", "report_download_failed", "operation_failed"})

    def test_error_defaults_operation_filter_and_safe_metadata(self):
        valid = self.add_event("operation_failed", properties={"operation": "export", "other": "secret"}, result="failure")
        self.add_event("operation_failed", session_id="ses_other123456", properties={}, result="failure")
        defaulted = self.add_event("analysis_create_failed", session_id="ses_analysis12", properties={}, result="failure")
        service = AdminReadService()
        items, _ = service.errors(self.start, self.start + timedelta(days=1), 50, None)
        self.assertEqual({item["errorId"] for item in items}, {str(valid), str(defaulted)})
        analysis = next(item for item in items if item["eventName"] == "analysis_create_failed")
        self.assertEqual((analysis["operation"], analysis["errorCode"], analysis["message"], analysis["requestId"]), ("analysis_create", "ANALYSIS_FAILED", "분석 요청을 처리하지 못했습니다.", None))
        detail = service.error_detail(valid)
        self.assertEqual(detail["error"]["safeMetadata"], {"requestId": None})
        self.assertNotIn("other", detail["error"]["safeMetadata"])

    def test_timeseries_bulk_loads_once_for_ninety_day_hour_range(self):
        end = self.start + timedelta(days=90)
        with self.sessions() as session:
            session.add(AnalyticsAdminAggregateState(id=1, data_through=end, refreshed_at=end))
            session.commit()
        service = AdminReadService()
        with patch.object(service, "_metric_sources", wraps=service._metric_sources) as bulk:
            points, through = service.timeseries(self.start, end, ZoneInfo("UTC"), "hour")
        self.assertEqual(len(points), 2160)
        self.assertEqual(bulk.call_count, 1)
        self.assertEqual(through, end)
        self.assertTrue(all(point["totalEvents"] == 0 for point in points))

    def test_timeseries_preserves_repeated_dst_hour_and_matches_summary(self):
        user = self.add_user()
        self.add_event("analysis_created", user_id=user, at=self.start + timedelta(minutes=5))
        self.add_event("report_viewed", user_id=user, at=self.start + timedelta(minutes=10))
        end = self.start + timedelta(hours=1)
        service = AdminReadService()
        service.refresh_aggregates(end)
        summary, _ = service.dashboard(self.start, end)
        points, _ = service.timeseries(self.start, end, ZoneInfo("UTC"), "hour")
        for key in ("totalEvents", "analysesCreated", "reportsViewed", "failures"):
            self.assertEqual(sum(point[key] for point in points), summary[key])

        dst_start = datetime(2026, 11, 1, 4, tzinfo=timezone.utc)
        dst_end = dst_start + timedelta(hours=4)
        with self.sessions() as session:
            state = session.get(AnalyticsAdminAggregateState, 1)
            state.data_through = dst_end
            session.commit()
        repeated, _ = service.timeseries(dst_start, dst_end, ZoneInfo("America/New_York"), "hour")
        self.assertEqual(len(repeated), 4)
        self.assertEqual(len({point["bucketStart"] for point in repeated}), 4)

    def test_error_group_counts_are_global_and_loaded_once(self):
        for index in range(3):
            self.add_event("analysis_create_failed", session_id=f"ses_same{index:08d}", at=self.start + timedelta(minutes=10), result="failure")
        self.add_event("analysis_create_failed", session_id="ses_otherpage1", at=self.start + timedelta(minutes=5), result="failure", page_name="other")
        self.add_event("operation_failed", session_id="ses_export1234", at=self.start + timedelta(minutes=4), properties={"operation": "export", "errorCode": "EXPORT_FAILED"}, result="failure")
        self.add_event("operation_failed", session_id="ses_missingop1", properties={}, result="failure")
        self.add_event("login_failed", session_id="ses_login12345", result="failure")
        service = AdminReadService()
        with patch.object(service, "_error_group_counts", wraps=service._error_group_counts) as grouped:
            first, cursor = service.errors(self.start, self.start + timedelta(days=1), 1, None)
        self.assertEqual(grouped.call_count, 1)
        self.assertEqual(first[0]["sameErrorCountInRange"], 3)
        self.assertIsNotNone(cursor)

        items, _ = service.errors(self.start, self.start + timedelta(days=1), 10, None)
        counts = {(item["eventName"], item["operation"], item["errorCode"], item["page"]["name"]): item["sameErrorCountInRange"] for item in items}
        self.assertEqual(counts[("analysis_create_failed", "analysis_create", "ANALYSIS_FAILED", "analysis")], 3)
        self.assertEqual(counts[("analysis_create_failed", "analysis_create", "ANALYSIS_FAILED", "other")], 1)
        self.assertEqual(counts[("operation_failed", "export", "EXPORT_FAILED", "analysis")], 1)
        self.assertNotIn("login_failed", {item["eventName"] for item in items})
        self.assertEqual(len(items), 5)

    def test_openapi_contains_only_p0_admin_read_paths(self):
        paths = app.openapi()["paths"]
        p0_paths = {
            "/api/v1/admin/dashboard/summary", "/api/v1/admin/dashboard/timeseries", "/api/v1/admin/users",
            "/api/v1/admin/users/{userId}", "/api/v1/admin/users/{userId}/activity", "/api/v1/admin/events",
            "/api/v1/admin/errors", "/api/v1/admin/errors/{errorId}", "/api/v1/admin/audit-logs",
        }
        self.assertEqual({path for path in paths if path.startswith("/api/v1/admin/") and "/auth/" not in path}, p0_paths)
        for path in p0_paths:
            self.assertEqual(set(paths[path]), {"get"})
        for path, schema in {
            "/api/v1/admin/dashboard/summary": "DashboardSummaryResponse",
            "/api/v1/admin/dashboard/timeseries": "DashboardTimeseriesResponse",
            "/api/v1/admin/users/{userId}": "UserDetailResponse",
            "/api/v1/admin/errors/{errorId}": "ErrorDetailResponse",
        }.items():
            self.assertEqual(paths[path]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"], f"#/components/schemas/{schema}")
        for path in (
            "/api/v1/admin/dashboard/top-pages", "/api/v1/admin/dashboard/top-events", "/api/v1/admin/events/stats",
            "/api/v1/admin/users/{user_id}/sessions", "/api/v1/admin/sessions/{session_id}", "/api/v1/admin/online-users",
        ):
            self.assertNotIn(path, paths)


if __name__ == "__main__":
    unittest.main()
