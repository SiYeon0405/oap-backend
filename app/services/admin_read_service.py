import base64
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import String, case, cast, delete, func, or_, select

from app.database.session import get_session
from app.models.admin import AdminAuditLog, AdminUser
from app.models.analytics import AnalyticsAdminAggregateState, AnalyticsAdminHourly, AnalyticsEvent
from app.models.user import User
from app.services.admin_security import mask_ip_address


FAILURE_EVENTS = frozenset({"analysis_create_failed", "report_download_failed", "operation_failed"})
ERROR_DEFAULTS = {
    "analysis_create_failed": ("analysis_create", "ANALYSIS_FAILED", "분석 요청을 처리하지 못했습니다."),
    "report_download_failed": ("report_download", "REPORT_DOWNLOAD_FAILED", "리포트를 다운로드하지 못했습니다."),
    "operation_failed": (None, "OPERATION_FAILED", "요청을 처리하지 못했습니다."),
}
SAFE_EVENT_PROPERTIES = frozenset({
    "pageName", "referrerType", "provider", "errorCode", "entryPoint", "requestId",
    "step", "reportType", "durationMs", "operation",
})
SAFE_AUDIT_METADATA = frozenset({"authMethod", "errorCode", "reason", "role"})


def encode_cursor(kind: str, filters: dict, values: list) -> str:
    raw = json.dumps({"k": kind, "f": filters, "v": values}, separators=(",", ":"), default=str).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str | None, kind: str, filters: dict) -> list | None:
    if not cursor:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        value = json.loads(raw)
        if value["k"] != kind or value["f"] != filters or not isinstance(value["v"], list):
            raise ValueError
        return value["v"]
    except Exception as exc:
        raise ValueError("invalid cursor") from exc


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _iso(value: datetime | None):
    return _utc(value).isoformat().replace("+00:00", "Z") if value else None


def _page(row):
    return {"path": row.path_template, "name": row.page_name} if row.page_name or row.path_template else None


def _target(row):
    return {"type": row.target_type, "id": row.target_id} if row.target_type or row.target_id else None


def _safe_properties(row):
    return {key: value for key, value in (row.properties or {}).items() if key in SAFE_EVENT_PROPERTIES}


def _user_status(value):
    return "active" if isinstance(value, str) and value.upper() == "ACTIVE" else "inactive"


class AdminReadService:
    def refresh_aggregates(self, cutoff: datetime | None = None) -> datetime:
        cutoff = _utc(cutoff or datetime.now(timezone.utc))
        with get_session() as session:
            grouped = defaultdict(int)
            for event in session.scalars(select(AnalyticsEvent).where(AnalyticsEvent.occurred_at < cutoff)):
                bucket = _utc(event.occurred_at).replace(minute=0, second=0, microsecond=0)
                grouped[(bucket, event.user_id, event.session_id, event.event_name, event.result)] += 1
            session.execute(delete(AnalyticsAdminHourly))
            session.add_all([
                AnalyticsAdminHourly(bucket_start=key[0], user_id=key[1], session_id=key[2], event_name=key[3], result=key[4], event_count=count)
                for key, count in grouped.items()
            ])
            state = session.get(AnalyticsAdminAggregateState, 1)
            if state is None:
                state = AnalyticsAdminAggregateState(id=1, data_through=cutoff, refreshed_at=datetime.now(timezone.utc))
                session.add(state)
            else:
                state.data_through = cutoff
                state.refreshed_at = datetime.now(timezone.utc)
            session.commit()
        return cutoff

    def dashboard(self, start: datetime, end: datetime, previous: bool = False):
        with get_session() as session:
            state = session.get(AnalyticsAdminAggregateState, 1)
            data_through = _utc(state.data_through) if state and state.data_through else None
            effective_end = min(end, data_through) if data_through else start
            current = self._metrics(session, start, effective_end)
            if not previous:
                return current, data_through
            duration = end - start
            prior = self._metrics(session, start - duration, min(start, data_through) if data_through else start - duration)
            return ({key: {"current": value, "previous": prior[key], "changeRate": None if prior[key] == 0 else (value - prior[key]) / prior[key]} for key, value in current.items()}, data_through)

    @staticmethod
    def _metric_sources(session, start, end):
        if end <= start:
            return [], []
        hour_start = start.replace(minute=0, second=0, microsecond=0) + (timedelta(hours=1) if start.minute or start.second or start.microsecond else timedelta())
        hour_end = end.replace(minute=0, second=0, microsecond=0)
        records = []
        if hour_start < hour_end:
            records.extend(session.scalars(select(AnalyticsAdminHourly).where(AnalyticsAdminHourly.bucket_start >= hour_start, AnalyticsAdminHourly.bucket_start < hour_end)).all())
        edges = []
        left_end = min(hour_start, end)
        if start < left_end:
            edges.append((AnalyticsEvent.occurred_at >= start) & (AnalyticsEvent.occurred_at < left_end))
        right_start = max(hour_end, start)
        if right_start < end and right_start >= left_end:
            edges.append((AnalyticsEvent.occurred_at >= right_start) & (AnalyticsEvent.occurred_at < end))
        events = session.scalars(select(AnalyticsEvent).where(or_(*edges))).all() if edges else []
        return records, events

    @staticmethod
    def _metrics(session, start, end):
        if end <= start:
            return {key: 0 for key in ("activeUsers", "anonymousSessions", "totalSessions", "totalEvents", "analysesCreated", "reportsViewed", "failures")}
        records, events = AdminReadService._metric_sources(session, start, end)
        users = {row.user_id for row in records if row.user_id is not None} | {row.user_id for row in events if row.user_id is not None}
        identified_sessions = {row.session_id for row in records if row.user_id is not None} | {row.session_id for row in events if row.user_id is not None}
        anonymous = ({row.session_id for row in records if row.user_id is None} | {row.session_id for row in events if row.user_id is None}) - identified_sessions
        sessions = {row.session_id for row in records} | {row.session_id for row in events}
        count = lambda name: sum(row.event_count for row in records if row.event_name == name) + sum(row.event_name == name for row in events)
        failures = sum(row.event_count for row in records if row.event_name in FAILURE_EVENTS) + sum(row.event_name in FAILURE_EVENTS for row in events)
        return {"activeUsers": len(users), "anonymousSessions": len(anonymous), "totalSessions": len(sessions), "totalEvents": sum(row.event_count for row in records) + len(events), "analysesCreated": count("analysis_created"), "reportsViewed": count("report_viewed"), "failures": failures}

    def timeseries(self, start, end, zone, interval):
        with get_session() as session:
            state = session.get(AnalyticsAdminAggregateState, 1)
            through = _utc(state.data_through) if state and state.data_through else None
            effective_end = min(end, through) if through else start
            records, events = self._metric_sources(session, start, effective_end)
        if interval == "hour":
            cursor = start.astimezone(zone).replace(minute=0, second=0, microsecond=0).astimezone(timezone.utc)
            advance = lambda value: value + timedelta(hours=1)
        else:
            cursor = start.astimezone(zone)
            cursor = cursor.replace(hour=0, minute=0, second=0, microsecond=0)
            advance = lambda value: value + timedelta(days=1)
        buckets = {}
        while cursor.astimezone(timezone.utc) < end:
            next_cursor = advance(cursor)
            bucket_start = cursor.astimezone(timezone.utc)
            buckets[bucket_start] = {"users": set(), "sessions": set(), "identified": set(), "anonymous": set(), "totalEvents": 0, "analysesCreated": 0, "reportsViewed": 0, "failures": 0}
            cursor = next_cursor

        def bucket_for(value):
            if interval == "hour":
                return _utc(value).replace(minute=0, second=0, microsecond=0)
            return _utc(value).astimezone(zone).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)

        def add(value, user_id, session_id, event_name, count):
            bucket = buckets.get(bucket_for(value))
            if bucket is None:
                return
            if user_id is None:
                bucket["anonymous"].add(session_id)
            else:
                bucket["users"].add(user_id)
                bucket["identified"].add(session_id)
            bucket["sessions"].add(session_id)
            bucket["totalEvents"] += count
            bucket["analysesCreated"] += count if event_name == "analysis_created" else 0
            bucket["reportsViewed"] += count if event_name == "report_viewed" else 0
            bucket["failures"] += count if event_name in FAILURE_EVENTS else 0

        for row in records:
            add(row.bucket_start, row.user_id, row.session_id, row.event_name, row.event_count)
        for event in events:
            add(event.occurred_at, event.user_id, event.session_id, event.event_name, 1)

        return [
            {"bucketStart": _iso(bucket_start), "activeUsers": len(bucket["users"]), "totalSessions": len(bucket["sessions"]), "totalEvents": bucket["totalEvents"], "analysesCreated": bucket["analysesCreated"], "reportsViewed": bucket["reportsViewed"], "failures": bucket["failures"]}
            for bucket_start, bucket in buckets.items()
        ], through

    def users(self, start, end, query, status_filter, sort, limit, cursor):
        filters = {"from": _iso(start), "to": _iso(end), "query": query, "status": status_filter, "sort": sort}
        values = decode_cursor(cursor, "users", filters)
        with get_session() as session:
            activity = select(AnalyticsEvent.user_id.label("uid"), func.max(AnalyticsEvent.occurred_at).label("last"), func.count().label("events"), func.count(func.distinct(AnalyticsEvent.session_id)).label("sessions"), func.count().filter(AnalyticsEvent.event_name == "analysis_created").label("analyses"), func.count().filter(AnalyticsEvent.event_name.in_(FAILURE_EVENTS)).label("failures")).where(AnalyticsEvent.occurred_at >= start, AnalyticsEvent.occurred_at < end, AnalyticsEvent.user_id.is_not(None)).group_by(AnalyticsEvent.user_id).subquery()
            stmt = select(User, activity).outerjoin(activity, User.id == activity.c.uid)
            if query:
                term = f"%{query}%"
                stmt = stmt.where(or_(cast(User.id, String).ilike(term), User.name.ilike(term), User.email.ilike(term)))
            if status_filter == "active": stmt = stmt.where(func.upper(User.status) == "ACTIVE")
            if status_filter == "inactive": stmt = stmt.where(or_(User.status.is_(None), func.upper(User.status) != "ACTIVE"))
            created = sort == "createdAt:desc"
            sort_col = User.created_at if created else func.coalesce(activity.c.last, datetime(1970, 1, 1, tzinfo=timezone.utc))
            desc = sort != "lastActivityAt:asc"
            if values:
                value, uid = datetime.fromisoformat(values[0].replace("Z", "+00:00")), int(values[1])
                stmt = stmt.where(or_(sort_col < value, (sort_col == value) & (User.id < uid)) if desc else or_(sort_col > value, (sort_col == value) & (User.id > uid)))
            stmt = stmt.order_by(sort_col.desc() if desc else sort_col.asc(), User.id.desc() if desc else User.id.asc()).limit(limit + 1)
            rows = session.execute(stmt).all()
            items = [{"id": row.User.id, "name": row.User.name, "email": row.User.email, "status": _user_status(row.User.status), "createdAt": _iso(row.User.created_at), "lastLoginAt": _iso(row.User.last_login_at), "lastActivityAt": _iso(row.last), "sessionCount": row.sessions or 0, "eventCount": row.events or 0, "analysisCreatedCount": row.analyses or 0, "failureCount": row.failures or 0} for row in rows[:limit]]
            next_value = None
            if len(rows) > limit:
                last = rows[limit - 1]
                key = last.User.created_at if created else (last.last or datetime(1970, 1, 1, tzinfo=timezone.utc))
                next_value = encode_cursor("users", filters, [_iso(key), last.User.id])
            return items, next_value

    def user_detail(self, user_id, start, end):
        with get_session() as session:
            user = session.get(User, user_id)
            if not user: return None
            events = session.scalars(select(AnalyticsEvent).where(AnalyticsEvent.user_id == user_id, AnalyticsEvent.occurred_at >= start, AnalyticsEvent.occurred_at < end)).all()
            last = max((event.occurred_at for event in events), default=None)
            return {"user": {"id": user.id, "name": user.name, "email": user.email, "status": _user_status(user.status), "createdAt": _iso(user.created_at), "lastLoginAt": _iso(user.last_login_at), "lastActivityAt": _iso(last)}, "metrics": {"sessionCount": len({e.session_id for e in events}), "eventCount": len(events), "analysisCreatedCount": sum(e.event_name == "analysis_created" for e in events), "reportViewedCount": sum(e.event_name == "report_viewed" for e in events), "failureCount": sum(e.event_name in FAILURE_EVENTS for e in events)}}

    def user_exists(self, user_id):
        with get_session() as session:
            return session.get(User, user_id) is not None

    def events(self, start, end, limit, cursor, *, user_id=None, event_name=None, session_id=None, result=None, page_path=None):
        filters = {"from": _iso(start), "to": _iso(end), "userId": user_id, "eventName": event_name, "sessionId": session_id, "result": result, "pagePath": page_path}
        values = decode_cursor(cursor, "events", filters)
        with get_session() as session:
            stmt = select(AnalyticsEvent, User).outerjoin(User, User.id == AnalyticsEvent.user_id).where(AnalyticsEvent.occurred_at >= start, AnalyticsEvent.occurred_at < end)
            if user_id is not None: stmt = stmt.where(AnalyticsEvent.user_id == user_id)
            if event_name: stmt = stmt.where(AnalyticsEvent.event_name == event_name)
            if session_id: stmt = stmt.where(AnalyticsEvent.session_id == session_id)
            if result == "none": stmt = stmt.where(AnalyticsEvent.result.is_(None))
            elif result: stmt = stmt.where(AnalyticsEvent.result == result)
            if page_path: stmt = stmt.where(AnalyticsEvent.path_template == page_path)
            if values:
                occurred, event_id = datetime.fromisoformat(values[0].replace("Z", "+00:00")), UUID(values[1])
                stmt = stmt.where(or_(AnalyticsEvent.occurred_at < occurred, (AnalyticsEvent.occurred_at == occurred) & (AnalyticsEvent.event_id < event_id)))
            rows = session.execute(stmt.order_by(AnalyticsEvent.occurred_at.desc(), AnalyticsEvent.event_id.desc()).limit(limit + 1)).all()
            items = [self._event_dto(event, user) for event, user in rows[:limit]]
            next_cursor = encode_cursor("events", filters, [_iso(rows[limit - 1][0].occurred_at), str(rows[limit - 1][0].event_id)]) if len(rows) > limit else None
            return items, next_cursor

    @staticmethod
    def _event_dto(event, user):
        return {"eventId": str(event.event_id), "eventName": event.event_name, "eventVersion": event.event_version, "occurredAt": _iso(event.occurred_at), "receivedAt": _iso(event.received_at), "user": {"id": user.id, "name": user.name, "email": user.email} if user else None, "sessionId": event.session_id, "page": _page(event), "target": _target(event), "result": event.result, "properties": _safe_properties(event)}

    @staticmethod
    def error_dto(event, user=None):
        operation, default_code, message = ERROR_DEFAULTS[event.event_name]
        properties = event.properties or {}
        operation = properties.get("operation") if event.event_name == "operation_failed" else operation
        if not operation: return None
        return {"errorId": str(event.event_id), "occurredAt": _iso(event.occurred_at), "eventName": event.event_name, "operation": operation, "errorCode": properties.get("errorCode") or default_code, "message": message, "requestId": None, "user": {"id": user.id, "name": user.name, "email": user.email} if user else None, "sessionId": event.session_id, "page": _page(event)}

    def errors(self, start, end, limit, cursor, error_code=None, operation=None, user_id=None):
        filters = {"from": _iso(start), "to": _iso(end), "errorCode": error_code, "operation": operation, "userId": user_id}
        values = decode_cursor(cursor, "errors", filters)
        with get_session() as session:
            stored_operation = AnalyticsEvent.properties["operation"].as_string()
            stored_error_code = AnalyticsEvent.properties["errorCode"].as_string()
            operation_value = case(
                (AnalyticsEvent.event_name == "analysis_create_failed", "analysis_create"),
                (AnalyticsEvent.event_name == "report_download_failed", "report_download"),
                else_=stored_operation,
            )
            error_code_value = case(
                (AnalyticsEvent.event_name == "analysis_create_failed", func.coalesce(stored_error_code, "ANALYSIS_FAILED")),
                (AnalyticsEvent.event_name == "report_download_failed", func.coalesce(stored_error_code, "REPORT_DOWNLOAD_FAILED")),
                else_=func.coalesce(stored_error_code, "OPERATION_FAILED"),
            )
            conditions = [AnalyticsEvent.occurred_at >= start, AnalyticsEvent.occurred_at < end, AnalyticsEvent.event_name.in_(FAILURE_EVENTS), operation_value.is_not(None), operation_value != ""]
            if user_id is not None: conditions.append(AnalyticsEvent.user_id == user_id)
            if error_code: conditions.append(error_code_value == error_code)
            if operation: conditions.append(operation_value == operation)
            base = select(AnalyticsEvent, User).outerjoin(User, User.id == AnalyticsEvent.user_id).where(*conditions)
            stmt = base
            if values:
                occurred, event_id = datetime.fromisoformat(values[0].replace("Z", "+00:00")), UUID(values[1])
                stmt = stmt.where(or_(AnalyticsEvent.occurred_at < occurred, (AnalyticsEvent.occurred_at == occurred) & (AnalyticsEvent.event_id < event_id)))
            rows = session.execute(stmt.order_by(AnalyticsEvent.occurred_at.desc(), AnalyticsEvent.event_id.desc()).limit(limit + 1)).all()
            selected = [(event, self.error_dto(event, user)) for event, user in rows[:limit]]
            counts = self._error_group_counts(session, conditions, operation_value, error_code_value)
            for event, dto in selected:
                dto["sameErrorCountInRange"] = counts[(event.event_name, dto["operation"], dto["errorCode"], event.page_name)]
            next_cursor = encode_cursor("errors", filters, [_iso(selected[-1][0].occurred_at), str(selected[-1][0].event_id)]) if len(rows) > limit else None
            return [dto for _, dto in selected], next_cursor

    @staticmethod
    def _error_group_counts(session, conditions, operation_value, error_code_value):
        rows = session.execute(
            select(
                AnalyticsEvent.event_name,
                operation_value.label("operation"),
                error_code_value.label("error_code"),
                AnalyticsEvent.page_name,
                func.count().label("count"),
            )
            .where(*conditions)
            .group_by(AnalyticsEvent.event_name, operation_value, error_code_value, AnalyticsEvent.page_name)
        )
        return {(row.event_name, row.operation, row.error_code, row.page_name): row.count for row in rows}

    def error_detail(self, error_id):
        with get_session() as session:
            row = session.execute(select(AnalyticsEvent, User).outerjoin(User, User.id == AnalyticsEvent.user_id).where(AnalyticsEvent.event_id == error_id, AnalyticsEvent.event_name.in_(FAILURE_EVENTS))).first()
            if not row: return None
            dto = self.error_dto(row.AnalyticsEvent, row.User)
            if not dto: return None
            dto["safeMetadata"] = {"requestId": (row.AnalyticsEvent.properties or {}).get("requestId")}
            previous = session.scalars(select(AnalyticsEvent).where(AnalyticsEvent.session_id == row.AnalyticsEvent.session_id, or_(AnalyticsEvent.occurred_at < row.AnalyticsEvent.occurred_at, (AnalyticsEvent.occurred_at == row.AnalyticsEvent.occurred_at) & (AnalyticsEvent.event_id < row.AnalyticsEvent.event_id))).order_by(AnalyticsEvent.occurred_at.desc(), AnalyticsEvent.event_id.desc()).limit(20)).all()
            return {"error": dto, "previousEvents": [{"eventId": str(e.event_id), "eventName": e.event_name, "occurredAt": _iso(e.occurred_at), "page": _page(e), "target": _target(e), "result": e.result} for e in previous]}

    @staticmethod
    def audit(session, admin_id, action, request_id, ip, target_id=None):
        session.add(AdminAuditLog(admin_id=admin_id, action=action, target_type="user" if target_id is not None else None, target_id=str(target_id) if target_id is not None else None, request_id=request_id, ip_address_masked=mask_ip_address(ip), result="success", audit_metadata={}))

    def write_audit(self, admin_id, action, request_id, ip, target_id=None):
        with get_session() as session:
            self.audit(session, admin_id, action, request_id, ip, target_id)
            session.commit()

    def audit_logs(self, start, end, limit, cursor, admin_id=None, action=None, success=None):
        filters = {"from": _iso(start), "to": _iso(end), "adminId": admin_id, "action": action, "success": success}
        values = decode_cursor(cursor, "audit", filters)
        with get_session() as session:
            stmt = select(AdminAuditLog, AdminUser).outerjoin(AdminUser, AdminUser.id == AdminAuditLog.admin_id).where(AdminAuditLog.occurred_at >= start, AdminAuditLog.occurred_at < end)
            if admin_id is not None: stmt = stmt.where(AdminAuditLog.admin_id == admin_id)
            if action: stmt = stmt.where(AdminAuditLog.action == action)
            if success is not None: stmt = stmt.where(AdminAuditLog.result == ("success" if success else "failure"))
            if values:
                occurred, row_id = datetime.fromisoformat(values[0].replace("Z", "+00:00")), int(values[1])
                stmt = stmt.where(or_(AdminAuditLog.occurred_at < occurred, (AdminAuditLog.occurred_at == occurred) & (AdminAuditLog.id < row_id)))
            rows = session.execute(stmt.order_by(AdminAuditLog.occurred_at.desc(), AdminAuditLog.id.desc()).limit(limit + 1)).all()
            items = [{"id": row.AdminAuditLog.id, "occurredAt": _iso(row.AdminAuditLog.occurred_at), "admin": {"id": row.AdminUser.id, "name": row.AdminUser.name, "email": row.AdminUser.email} if row.AdminUser else None, "action": row.AdminAuditLog.action, "success": row.AdminAuditLog.result == "success", "target": {"type": row.AdminAuditLog.target_type, "id": row.AdminAuditLog.target_id} if row.AdminAuditLog.target_type or row.AdminAuditLog.target_id else None, "requestId": row.AdminAuditLog.request_id, "maskedIp": row.AdminAuditLog.ip_address_masked, "metadata": {k: v for k, v in (row.AdminAuditLog.audit_metadata or {}).items() if k in SAFE_AUDIT_METADATA}} for row in rows[:limit]]
            next_cursor = encode_cursor("audit", filters, [_iso(rows[limit - 1].AdminAuditLog.occurred_at), rows[limit - 1].AdminAuditLog.id]) if len(rows) > limit else None
            return items, next_cursor
