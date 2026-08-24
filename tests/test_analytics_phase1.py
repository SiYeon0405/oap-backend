import os
import threading
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import CheckConstraint, create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.models.analytics import AnalyticsEvent, AnalyticsSession
from app.models.base import Base
from app.models.user import User
from app.schemas.analytics import AnalyticsEventInput
from app.services.analytics_service import AnalyticsService


def event_payload(**changes):
    payload = {
        "eventId": str(uuid4()),
        "eventName": "page_viewed",
        "eventVersion": 1,
        "sessionId": "ses_abcdefgh1234",
        "occurredAt": datetime.now(timezone.utc).isoformat(),
        "page": {"name": "home", "pathTemplate": "/analysis/{requestId}"},
        "properties": {"pageName": "home", "referrerType": "direct"},
    }
    payload.update(changes)
    return payload


class AnalyticsApiTest(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {"JWT_SECRET": "test-secret"}, clear=True)
        self.environment.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.environment.stop()

    def post(self, events, **kwargs):
        return self.client.post("/api/v1/analytics/events/batch", json={"events": events}, **kwargs)

    def test_valid_anonymous_event_and_refresh_only(self):
        stored = SimpleNamespace(accepted=1, rejected=0, errors=None)
        with patch("app.api.analytics.AnalyticsService.store_batch", return_value=stored) as store:
            response = self.post([event_payload()], headers={"Cookie": "refresh_token=unused"})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json(), {"accepted": 1, "rejected": 0})
        self.assertIsNone(store.call_args.args[1])

    def test_valid_access_cookie_uses_authenticated_user(self):
        stored = SimpleNamespace(accepted=1, rejected=0, errors=None)
        with patch("app.api.analytics.AuthService.get_current_user", return_value=SimpleNamespace(id=42)), patch(
            "app.api.analytics.AnalyticsService.store_batch", return_value=stored
        ) as store:
            response = self.post([event_payload()], headers={"Cookie": "access_token=valid"})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(store.call_args.args[1], 42)

    def test_invalid_access_cookie_is_401(self):
        from app.services.auth_service import InvalidCredentialsError

        with patch("app.api.analytics.AuthService.get_current_user", side_effect=InvalidCredentialsError):
            response = self.post([event_payload()], headers={"Cookie": "access_token=bad"})
        self.assertEqual(response.status_code, 401)

    def test_envelope_rejections(self):
        self.assertEqual(self.client.post("/api/v1/analytics/events/batch", json={}).status_code, 422)
        self.assertEqual(self.post([]).status_code, 422)
        self.assertEqual(self.post([event_payload() for _ in range(51)]).status_code, 422)
        self.assertEqual(
            self.client.post("/api/v1/analytics/events/batch", content=b"{broken", headers={"content-type": "application/json"}).status_code,
            422,
        )

    def test_actual_body_over_64kb_is_413(self):
        body = b'{"events":[]}' + b" " * (64 * 1024)
        response = self.client.post(
            "/api/v1/analytics/events/batch",
            content=body,
            headers={"content-type": "application/json", "content-length": "1"},
        )
        self.assertEqual(response.status_code, 413)

    def test_individual_validation_is_partial_and_total_is_stable(self):
        invalid = [
            event_payload(eventName="unknown"),
            event_payload(eventVersion=2),
            event_payload(userId=7),
            event_payload(properties={"answer": "secret"}),
            event_payload(properties={"unknown": "x"}),
            event_payload(properties={"pageName": ["nested"]}),
            event_payload(occurredAt=datetime.now().isoformat()),
            event_payload(occurredAt=(datetime.now(timezone.utc) + timedelta(minutes=6)).isoformat()),
            event_payload(occurredAt=(datetime.now(timezone.utc) - timedelta(days=91)).isoformat()),
            event_payload(sessionId="bad"),
            event_payload(page={"name": "home", "pathTemplate": "/analysis/123"}),
            event_payload(page={"name": "home", "extra": "x"}),
        ]
        stored = SimpleNamespace(accepted=1, rejected=0, errors=None)
        with patch("app.api.analytics.AnalyticsService.store_batch", return_value=stored):
            response = self.post([event_payload(), *invalid])
        data = response.json()
        self.assertEqual(response.status_code, 202)
        self.assertEqual(data["accepted"], 1)
        self.assertEqual(data["rejected"], len(invalid))
        self.assertEqual(data["accepted"] + data["rejected"], 1 + len(invalid))
        self.assertIn("errors", data)
        self.assertNotIn("duplicates", data)
        self.assertNotIn("secret", response.text)

    def test_db_failure_is_not_reported_as_partial_success(self):
        with patch("app.api.analytics.AnalyticsService.store_batch", side_effect=RuntimeError("database secret")):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.post("/api/v1/analytics/events/batch", json={"events": [event_payload()]})
            client.close()
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("database secret", response.text)


class AnalyticsServiceTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.engine = create_engine(
            f"sqlite:///{self.temp_dir.name}/analytics.db",
            connect_args={"check_same_thread": False},
        )
        def configure_sqlite(dbapi, _):
            dbapi.execute("PRAGMA foreign_keys=ON")
            dbapi.create_function("now", 0, lambda: datetime.now(timezone.utc).isoformat(" "))

        event.listen(self.engine, "connect", configure_sqlite)
        Base.metadata.create_all(self.engine, tables=[User.__table__, AnalyticsSession.__table__, AnalyticsEvent.__table__])
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.patch = patch("app.services.analytics_service.get_session", side_effect=self.sessions)
        self.patch.start()
        with self.sessions() as session:
            session.add_all([
                User(id=1, email="a@example.com", password_hash="x", name="A", status="ACTIVE"),
                User(id=2, email="b@example.com", password_hash="x", name="B", status="ACTIVE"),
            ])
            session.commit()

    def tearDown(self):
        self.patch.stop()
        self.engine.dispose()
        self.temp_dir.cleanup()

    @staticmethod
    def parsed(**changes):
        return AnalyticsEventInput.model_validate(event_payload(**changes))

    def test_duplicates_and_batch_duplicates_create_one_row(self):
        item = self.parsed()
        first = AnalyticsService().store_batch([item, item], None)
        second = AnalyticsService().store_batch([item], None)
        self.assertEqual((first.accepted, first.rejected), (2, 0))
        self.assertEqual((second.accepted, second.rejected), (1, 0))
        with self.sessions() as session:
            self.assertEqual(len(session.scalars(select(AnalyticsEvent)).all()), 1)

    def test_duplicate_id_with_different_payload_is_accepted_without_phantom_session(self):
        item = self.parsed()
        AnalyticsService().store_batch([item], None)
        conflicting = self.parsed(
            eventId=str(item.eventId),
            sessionId="ses_different1234",
        )
        result = AnalyticsService().store_batch([conflicting], None)
        self.assertEqual((result.accepted, result.rejected), (1, 0))
        self.assertIsNone(result.errors)
        with self.sessions() as session:
            self.assertIsNone(session.get(AnalyticsSession, conflicting.sessionId))

    def test_anonymous_session_promotes_and_blocks_wrong_owners(self):
        first = self.parsed()
        AnalyticsService().store_batch([first], None)
        promoted = self.parsed(sessionId=first.sessionId)
        self.assertEqual(AnalyticsService().store_batch([promoted], 1).accepted, 1)
        stolen = self.parsed(sessionId=first.sessionId)
        self.assertEqual(AnalyticsService().store_batch([stolen], 2).rejected, 1)
        anonymous = self.parsed(sessionId=first.sessionId)
        self.assertEqual(AnalyticsService().store_batch([anonymous], None).rejected, 1)
        with self.sessions() as session:
            row = session.get(AnalyticsSession, first.sessionId)
            self.assertEqual(row.user_id, 1)

    def test_last_activity_updates_without_server_session_split(self):
        first = self.parsed(occurredAt=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat())
        later = self.parsed(sessionId=first.sessionId)
        AnalyticsService().store_batch([first, later], None)
        with self.sessions() as session:
            row = session.get(AnalyticsSession, first.sessionId)
            self.assertEqual(row.last_activity_at.replace(tzinfo=timezone.utc), later.occurredAt)

    def test_delete_user_sets_analytics_owner_null(self):
        item = self.parsed()
        AnalyticsService().store_batch([item], 1)
        with self.sessions() as session:
            session.delete(session.get(User, 1))
            session.commit()
        with self.sessions() as session:
            self.assertIsNone(session.get(AnalyticsSession, item.sessionId).user_id)
            self.assertIsNone(session.scalar(select(AnalyticsEvent)).user_id)

    def test_model_contract_has_fk_checks_unique_and_required_indexes(self):
        event_table = AnalyticsEvent.__table__
        session_table = AnalyticsSession.__table__
        self.assertEqual(str(event_table.c.user_id.type), "INTEGER")
        self.assertEqual(str(session_table.c.user_id.type), "INTEGER")
        self.assertEqual(next(iter(event_table.c.user_id.foreign_keys)).ondelete, "SET NULL")
        self.assertEqual(next(iter(session_table.c.user_id.foreign_keys)).ondelete, "SET NULL")
        self.assertTrue(event_table.c.event_id.unique)
        checks = {constraint.name for constraint in event_table.constraints if isinstance(constraint, CheckConstraint)}
        self.assertEqual(checks, {"ck_analytics_events_version", "ck_analytics_events_result"})
        self.assertEqual(
            {index.name for index in event_table.indexes},
            {
                "ix_analytics_events_occurred_name",
                "ix_analytics_events_user_occurred",
                "ix_analytics_events_session_occurred",
                "ix_analytics_events_user_cursor",
                "ix_analytics_events_session_cursor",
                "ix_analytics_events_result_occurred",
            },
        )
        self.assertEqual(
            {index.name for index in session_table.indexes},
            {"ix_analytics_sessions_user_activity", "ix_analytics_sessions_last_activity"},
        )

    @unittest.skip("requires PostgreSQL row-level concurrency; SQLite permits one writer")
    def test_concurrent_duplicate_has_one_event(self):
        item = self.parsed()
        with self.sessions() as session:
            session.add(
                AnalyticsSession(
                    session_id=item.sessionId,
                    started_at=item.occurredAt,
                    last_activity_at=item.occurredAt,
                )
            )
            session.commit()
        barrier = threading.Barrier(2)
        results = []

        def store():
            barrier.wait()
            results.append(AnalyticsService().store_batch([item], None))

        threads = [threading.Thread(target=store) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        with self.sessions() as session:
            self.assertEqual(len(session.scalars(select(AnalyticsEvent)).all()), 1)
        self.assertEqual(sum(result.accepted for result in results), 2)


if __name__ == "__main__":
    unittest.main()
