import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated, Callable, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Path, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from app.api.admin_auth import AdminApiError, require_admin_permission
from app.schemas.admin_read import (
    DashboardSummaryResponse,
    DashboardTimeseriesResponse,
    ErrorDetailResponse,
    PageResponse,
    UserDetailResponse,
    validate_range,
)
from app.services.admin_read_service import AdminReadService
from app.services.analytics_service import EVENT_PROPERTIES


logger = logging.getLogger(__name__)


def _error(request, status_code, code, message):
    return JSONResponse(status_code=status_code, content={"error": {"code": code, "message": message, "requestId": request.state.admin_request_id}})


class AdminReadRoute(APIRoute):
    def get_route_handler(self) -> Callable:
        original = super().get_route_handler()

        async def handler(request: Request):
            request.state.admin_request_id = f"http_req_{uuid4().hex}"
            try:
                response = await original(request)
            except (RequestValidationError, ValueError):
                response = _error(request, 422, "ADMIN_QUERY_INVALID", "조회 조건이 올바르지 않습니다.")
            except AdminApiError as exc:
                response = _error(request, exc.status_code, exc.code, exc.message)
            except Exception:
                logger.exception("Administrator read request failed: request_id=%s", request.state.admin_request_id)
                response = _error(request, 500, "ADMIN_INTERNAL_ERROR", "관리자 조회 요청을 처리하지 못했습니다.")
            response.headers["Cache-Control"] = "private, no-store"
            response.headers["Pragma"] = "no-cache"
            return response

        return handler


router = APIRouter(prefix="/api/v1/admin", tags=["admin-read"], route_class=AdminReadRoute)


def _range(from_: datetime | None, to: datetime | None, timezone_name: str):
    start, end, zone = validate_range(from_, to, timezone_name)
    return start, end, zone, {"from": start.isoformat().replace("+00:00", "Z"), "to": end.isoformat().replace("+00:00", "Z"), "timezone": timezone_name}


def _page(items, cursor):
    return {"items": items, "page": {"nextCursor": cursor, "hasNext": cursor is not None}}


def _audit(request, admin, action, target=None):
    AdminReadService().write_audit(admin.id, action, request.state.admin_request_id, request.client.host if request.client else None, target)


@router.get("/dashboard/summary", response_model=DashboardSummaryResponse)
def dashboard_summary(request: Request, admin=Depends(require_admin_permission("dashboard:read")), from_: datetime | None = Query(None, alias="from"), to: datetime | None = None, timezone_name: str = Query("Asia/Seoul", alias="timezone")):
    start, end, _, range_dto = _range(from_, to, timezone_name)
    metrics, through = AdminReadService().dashboard(start, end, previous=True)
    return {"range": range_dto, "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "dataThrough": through.isoformat().replace("+00:00", "Z") if through else None, "metrics": metrics}


@router.get("/dashboard/timeseries", response_model=DashboardTimeseriesResponse)
def dashboard_timeseries(request: Request, admin=Depends(require_admin_permission("dashboard:read")), from_: datetime | None = Query(None, alias="from"), to: datetime | None = None, timezone_name: str = Query("Asia/Seoul", alias="timezone"), interval: Literal["hour", "day"] | None = None):
    start, end, zone, range_dto = _range(from_, to, timezone_name)
    interval = interval or ("hour" if end - start <= timedelta(hours=48) else "day")
    points, through = AdminReadService().timeseries(start, end, zone, interval)
    return {"range": {**range_dto, "interval": interval}, "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "dataThrough": through.isoformat().replace("+00:00", "Z") if through else None, "points": points}


@router.get("/users", response_model=PageResponse)
def users(request: Request, admin=Depends(require_admin_permission("users:read")), from_: datetime | None = Query(None, alias="from"), to: datetime | None = None, timezone_name: str = Query("Asia/Seoul", alias="timezone"), query: str | None = Query(None, max_length=100), status_filter: Literal["active", "inactive", "all"] = Query("all", alias="status"), sort: Literal["lastActivityAt:desc", "lastActivityAt:asc", "createdAt:desc"] = "lastActivityAt:desc", limit: int = Query(50, ge=1, le=100), cursor: str | None = None):
    start, end, _, _ = _range(from_, to, timezone_name)
    query = query.strip() if query else None
    items, next_cursor = AdminReadService().users(start, end, query, status_filter, sort, limit, cursor)
    _audit(request, admin, "admin_users_viewed")
    return _page(items, next_cursor)


@router.get("/users/{userId}", response_model=UserDetailResponse)
def user_detail(user_id: Annotated[int, Path(alias="userId")], request: Request, admin=Depends(require_admin_permission("users:read")), from_: datetime | None = Query(None, alias="from"), to: datetime | None = None, timezone_name: str = Query("Asia/Seoul", alias="timezone")):
    start, end, _, range_dto = _range(from_, to, timezone_name)
    result = AdminReadService().user_detail(user_id, start, end)
    if result is None: raise AdminApiError(404, "ADMIN_RESOURCE_NOT_FOUND", "대상을 찾을 수 없습니다.")
    _audit(request, admin, "admin_user_viewed", user_id)
    return {**result, "range": range_dto}


@router.get("/users/{userId}/activity", response_model=PageResponse)
def user_activity(user_id: Annotated[int, Path(alias="userId")], request: Request, admin=Depends(require_admin_permission("users:read")), from_: datetime | None = Query(None, alias="from"), to: datetime | None = None, timezone_name: str = Query("Asia/Seoul", alias="timezone"), event_name: str | None = Query(None, alias="eventName"), limit: int = Query(50, ge=1, le=100), cursor: str | None = None):
    start, end, _, _ = _range(from_, to, timezone_name)
    if event_name and event_name not in EVENT_PROPERTIES: raise ValueError
    if not AdminReadService().user_exists(user_id): raise AdminApiError(404, "ADMIN_RESOURCE_NOT_FOUND", "대상을 찾을 수 없습니다.")
    items, next_cursor = AdminReadService().events(start, end, limit, cursor, user_id=user_id, event_name=event_name)
    items = [{key: item[key] for key in ("eventId", "eventName", "occurredAt", "receivedAt", "sessionId", "page", "target", "result", "properties")} for item in items]
    _audit(request, admin, "admin_user_activity_viewed", user_id)
    return _page(items, next_cursor)


@router.get("/events", response_model=PageResponse)
def events(admin=Depends(require_admin_permission("events:read")), from_: datetime | None = Query(None, alias="from"), to: datetime | None = None, timezone_name: str = Query("Asia/Seoul", alias="timezone"), event_name: str | None = Query(None, alias="eventName"), user_id: int | None = Query(None, alias="userId"), session_id: str | None = Query(None, alias="sessionId"), result: Literal["success", "failure", "none"] | None = None, page_path: str | None = Query(None, alias="pagePath"), limit: int = Query(50, ge=1, le=100), cursor: str | None = None):
    start, end, _, _ = _range(from_, to, timezone_name)
    if event_name and event_name not in EVENT_PROPERTIES: raise ValueError
    items, next_cursor = AdminReadService().events(start, end, limit, cursor, user_id=user_id, event_name=event_name, session_id=session_id, result=result, page_path=page_path)
    return _page(items, next_cursor)


@router.get("/errors", response_model=PageResponse)
def errors(admin=Depends(require_admin_permission("errors:read")), from_: datetime | None = Query(None, alias="from"), to: datetime | None = None, timezone_name: str = Query("Asia/Seoul", alias="timezone"), error_code: str | None = Query(None, alias="errorCode"), operation: str | None = None, user_id: int | None = Query(None, alias="userId"), limit: int = Query(50, ge=1, le=100), cursor: str | None = None):
    start, end, _, _ = _range(from_, to, timezone_name)
    items, next_cursor = AdminReadService().errors(start, end, limit, cursor, error_code, operation, user_id)
    return _page(items, next_cursor)


@router.get("/errors/{errorId}", response_model=ErrorDetailResponse)
def error_detail(error_id: Annotated[UUID, Path(alias="errorId")], admin=Depends(require_admin_permission("errors:read"))):
    result = AdminReadService().error_detail(error_id)
    if result is None: raise AdminApiError(404, "ADMIN_RESOURCE_NOT_FOUND", "대상을 찾을 수 없습니다.")
    return result


@router.get("/audit-logs", response_model=PageResponse)
def audit_logs(request: Request, admin=Depends(require_admin_permission("audit:read")), from_: datetime | None = Query(None, alias="from"), to: datetime | None = None, timezone_name: str = Query("Asia/Seoul", alias="timezone"), admin_id: int | None = Query(None, alias="adminId"), action: str | None = None, success: bool | None = None, limit: int = Query(50, ge=1, le=100), cursor: str | None = None):
    start, end, _, _ = _range(from_, to, timezone_name)
    items, next_cursor = AdminReadService().audit_logs(start, end, limit, cursor, admin_id, action, success)
    _audit(request, admin, "admin_audit_logs_viewed")
    return _page(items, next_cursor)
