from datetime import datetime, timedelta, timezone
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database.session import get_session
from app.models.analytics import AnalyticsEvent, AnalyticsSession
from app.schemas.analytics import AnalyticsBatchResponse, AnalyticsError, AnalyticsEventInput


EVENT_PROPERTIES = {
    "page_viewed": {"pageName": (str, 64), "referrerType": (str, 32)},
    "login_succeeded": {"provider": (str, 32)},
    "login_failed": {"provider": (str, 32), "errorCode": (str, 64)},
    "analysis_create_clicked": {"entryPoint": (str, 64)},
    "analysis_created": {"requestId": (int, None)},
    "analysis_create_failed": {"errorCode": (str, 64)},
    "interview_answer_submitted": {"requestId": (int, None), "step": (int, 1000)},
    "analysis_started": {"requestId": (int, None)},
    "report_viewed": {"requestId": (int, None)},
    "report_download_clicked": {"reportType": (str, 32)},
    "report_download_succeeded": {"durationMs": (int, 86_400_000)},
    "report_download_failed": {"errorCode": (str, 64)},
    "operation_failed": {"operation": (str, 64), "errorCode": (str, 64)},
}
SENSITIVE_KEYS = {
    "password", "passwd", "accesstoken", "refreshtoken", "token", "cookie",
    "authorization", "answer", "question", "content", "description",
    "servicedescription", "reportcontent", "keyword", "query", "dom",
    "querystring", "searchquery", "domcontent",
}
SAFE_PROPERTY_VALUE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]*$")
MAX_FUTURE = timedelta(minutes=5)
MAX_AGE = timedelta(days=90)


class SessionOwnershipError(Exception):
    pass


def validate_event_contract(event: AnalyticsEventInput, now: datetime) -> str | None:
    if event.eventName not in EVENT_PROPERTIES:
        return "INVALID_EVENT_NAME"
    if event.occurredAt >= now + MAX_FUTURE:
        return "EVENT_TIME_IN_FUTURE"
    if event.occurredAt < now - MAX_AGE:
        return "EVENT_TIME_TOO_OLD"

    allowed = EVENT_PROPERTIES[event.eventName]
    for key, value in event.properties.items():
        normalized = re_normalize_key(key)
        if normalized in SENSITIVE_KEYS:
            return "SENSITIVE_PROPERTY"
        if key not in allowed:
            return "UNKNOWN_PROPERTY"
        expected_type, limit = allowed[key]
        if isinstance(value, (dict, list)) or isinstance(value, bool):
            return "INVALID_PROPERTY_VALUE"
        if expected_type is str:
            if (
                not isinstance(value, str)
                or len(value) > limit
                or not SAFE_PROPERTY_VALUE.fullmatch(value)
            ):
                return "INVALID_PROPERTY_VALUE"
        elif not isinstance(value, int):
            return "INVALID_PROPERTY_VALUE"
        elif key in {"requestId", "step"} and value <= 0:
            return "INVALID_PROPERTY_VALUE"
        elif key == "durationMs" and (value < 0 or value > limit):
            return "INVALID_PROPERTY_VALUE"
        elif limit is not None and value > limit:
            return "INVALID_PROPERTY_VALUE"
    return None


def re_normalize_key(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


class AnalyticsService:
    def store_batch(
        self,
        events: list[AnalyticsEventInput],
        user_id: int | None,
    ) -> AnalyticsBatchResponse:
        accepted = rejected = 0
        errors: list[AnalyticsError] = []
        with get_session() as session:
            for event in events:
                try:
                    with session.begin_nested():
                        ownership_error = self._claim_session(session, event, user_id)
                        if ownership_error:
                            raise SessionOwnershipError(ownership_error)
                        session.add(
                            AnalyticsEvent(
                                event_id=event.eventId,
                                event_name=event.eventName,
                                event_version=event.eventVersion,
                                user_id=user_id,
                                session_id=event.sessionId,
                                occurred_at=event.occurredAt,
                                page_name=event.page.name if event.page else None,
                                path_template=event.page.pathTemplate if event.page else None,
                                target_type=event.target.type if event.target else None,
                                target_id=event.target.id if event.target else None,
                                result=event.result,
                                properties=event.properties,
                            )
                        )
                        session.flush()
                    accepted += 1
                except SessionOwnershipError:
                    rejected += 1
                    errors.append(
                        AnalyticsError(eventId=str(event.eventId), code="INVALID_EVENT")
                    )
                except IntegrityError as exc:
                    existing = self._existing_event(session, event.eventId)
                    if existing is None:
                        raise exc
                    accepted += 1
            session.commit()
        return AnalyticsBatchResponse(
            accepted=accepted,
            rejected=rejected,
            errors=errors or None,
        )

    @staticmethod
    def _existing_event(session, event_id) -> AnalyticsEvent | None:
        return session.scalar(
            select(AnalyticsEvent).where(AnalyticsEvent.event_id == event_id)
        )

    @staticmethod
    def _claim_session(session, event: AnalyticsEventInput, user_id: int | None) -> str | None:
        analytics_session = session.scalar(
            select(AnalyticsSession)
            .where(AnalyticsSession.session_id == event.sessionId)
            .with_for_update()
        )
        if analytics_session is None:
            try:
                with session.begin_nested():
                    analytics_session = AnalyticsSession(
                        session_id=event.sessionId,
                        user_id=user_id,
                        started_at=event.occurredAt,
                        last_activity_at=event.occurredAt,
                        entry_page=event.page.name if event.page else None,
                    )
                    session.add(analytics_session)
                    session.flush()
            except IntegrityError:
                analytics_session = session.scalar(
                    select(AnalyticsSession)
                    .where(AnalyticsSession.session_id == event.sessionId)
                    .with_for_update()
                )
                if analytics_session is None:
                    raise

        if analytics_session.user_id is not None and user_id is None:
            return "SESSION_OWNERSHIP_MISMATCH"
        if analytics_session.user_id is not None and analytics_session.user_id != user_id:
            return "SESSION_OWNERSHIP_MISMATCH"
        if analytics_session.user_id is None and user_id is not None:
            analytics_session.user_id = user_id
        if event.occurredAt > AnalyticsService._as_utc(analytics_session.last_activity_at):
            analytics_session.last_activity_at = event.occurredAt
        return None

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
