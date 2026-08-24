from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field


class AdminReadModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class RangeResponse(AdminReadModel):
    from_: datetime = Field(alias="from")
    to: datetime
    timezone: str


class MetricResponse(AdminReadModel):
    current: int
    previous: int
    changeRate: float | None


class DashboardMetricsResponse(AdminReadModel):
    activeUsers: MetricResponse
    anonymousSessions: MetricResponse
    totalSessions: MetricResponse
    totalEvents: MetricResponse
    analysesCreated: MetricResponse
    reportsViewed: MetricResponse
    failures: MetricResponse


class DashboardSummaryResponse(AdminReadModel):
    range: RangeResponse
    generatedAt: datetime
    dataThrough: datetime | None
    metrics: DashboardMetricsResponse


class TimeseriesRangeResponse(RangeResponse):
    interval: Literal["hour", "day"]


class TimeseriesPointResponse(AdminReadModel):
    bucketStart: datetime
    activeUsers: int
    totalSessions: int
    totalEvents: int
    analysesCreated: int
    reportsViewed: int
    failures: int


class DashboardTimeseriesResponse(AdminReadModel):
    range: TimeseriesRangeResponse
    generatedAt: datetime
    dataThrough: datetime | None
    points: list[TimeseriesPointResponse]


class UserResponse(AdminReadModel):
    id: int
    name: str
    email: str
    status: Literal["active", "inactive"]
    createdAt: datetime
    lastLoginAt: datetime | None
    lastActivityAt: datetime | None


class UserMetricsResponse(AdminReadModel):
    sessionCount: int
    eventCount: int
    analysisCreatedCount: int
    reportViewedCount: int
    failureCount: int


class UserDetailResponse(AdminReadModel):
    user: UserResponse
    range: RangeResponse
    metrics: UserMetricsResponse


class EventUserResponse(AdminReadModel):
    id: int
    name: str
    email: str


class PageLocationResponse(AdminReadModel):
    path: str | None
    name: str | None


class TargetResponse(AdminReadModel):
    type: str | None
    id: str | None


class SafeMetadataResponse(AdminReadModel):
    requestId: int | None = None


class ErrorResponse(AdminReadModel):
    errorId: UUID
    occurredAt: datetime
    eventName: str
    operation: str
    errorCode: str
    message: str
    requestId: str | None
    user: EventUserResponse | None
    sessionId: str
    page: PageLocationResponse | None
    safeMetadata: SafeMetadataResponse


class PreviousEventResponse(AdminReadModel):
    eventId: UUID
    eventName: str
    occurredAt: datetime
    page: PageLocationResponse | None
    target: TargetResponse | None
    result: Literal["success", "failure"] | None


class ErrorDetailResponse(AdminReadModel):
    error: ErrorResponse
    previousEvents: list[PreviousEventResponse]


class PageInfo(BaseModel):
    nextCursor: str | None
    hasNext: bool


class PageResponse(BaseModel):
    items: list[dict]
    page: PageInfo


def validate_range(start: datetime | None, end: datetime | None, timezone_name: str):
    now = datetime.now(timezone.utc)
    end = end or now
    start = start or end - timedelta(days=7)
    if start.tzinfo is None or end.tzinfo is None or start >= end or end - start > timedelta(days=90):
        raise ValueError("invalid range")
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("invalid timezone") from exc
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc), zone
