import re
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


SESSION_ID_PATTERN = re.compile(r"^ses_[A-Za-z0-9_-]{8,124}$")
PATH_SEGMENT_PATTERN = re.compile(
    r"^[A-Za-z][A-Za-z0-9_.-]*$|^\{[A-Za-z][A-Za-z0-9]*\}$"
)
UUID_SEGMENT_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnalyticsPage(StrictModel):
    name: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z][A-Za-z0-9_.:-]*$",
    )
    pathTemplate: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("pathTemplate")
    @classmethod
    def validate_path_template(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.startswith("/") or "?" in value or "#" in value:
            raise ValueError("invalid path template")
        for segment in filter(None, value.split("/")):
            if segment.isdigit() or UUID_SEGMENT_PATTERN.fullmatch(segment):
                raise ValueError("path identifiers must be templated")
            if not PATH_SEGMENT_PATTERN.fullmatch(segment):
                raise ValueError("invalid path template")
        return value


class AnalyticsTarget(StrictModel):
    type: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class AnalyticsEventInput(StrictModel):
    eventId: UUID
    eventName: str = Field(min_length=1, max_length=64)
    eventVersion: int
    sessionId: str = Field(min_length=12, max_length=128)
    occurredAt: datetime
    page: AnalyticsPage | None = None
    target: AnalyticsTarget | None = None
    result: Literal["success", "failure"] | None = None
    properties: dict[str, Any] = Field(default_factory=dict)

    @field_validator("eventVersion")
    @classmethod
    def validate_version(cls, value: int) -> int:
        if isinstance(value, bool) or value != 1:
            raise ValueError("unsupported event version")
        return value

    @field_validator("sessionId")
    @classmethod
    def validate_session_id(cls, value: str) -> str:
        if not SESSION_ID_PATTERN.fullmatch(value):
            raise ValueError("invalid session id")
        return value

    @field_validator("occurredAt")
    @classmethod
    def validate_occurred_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timezone is required")
        return value.astimezone(timezone.utc)


class AnalyticsBatchEnvelope(StrictModel):
    events: list[Any] = Field(min_length=1, max_length=50)


class AnalyticsError(BaseModel):
    eventId: str
    code: str


class AnalyticsBatchResponse(BaseModel):
    accepted: int
    rejected: int
    errors: list[AnalyticsError] | None = None
