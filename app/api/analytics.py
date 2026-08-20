import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import ValidationError

from app.models.user import User
from app.schemas.analytics import (
    AnalyticsBatchEnvelope,
    AnalyticsBatchResponse,
    AnalyticsError,
    AnalyticsEventInput,
)
from app.services.analytics_service import AnalyticsService, validate_event_contract
from app.services.auth_service import AuthService, InvalidCredentialsError


router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])
MAX_BODY_BYTES = 64 * 1024


@router.post(
    "/events/batch",
    response_model=AnalyticsBatchResponse,
    response_model_exclude_none=True,
    status_code=status.HTTP_202_ACCEPTED,
    description="Accepts validated analytics events for collection.",
    responses={401: {}, 413: {}, 422: {}, 500: {}},
)
async def collect_events(request: Request):
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_BODY_BYTES:
                raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
    chunks = []
    body_size = 0
    async for chunk in request.stream():
        body_size += len(chunk)
        if body_size > MAX_BODY_BYTES:
            raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE)
        chunks.append(chunk)
    body = b"".join(chunks)
    try:
        envelope = AnalyticsBatchEnvelope.model_validate(json.loads(body))
    except (json.JSONDecodeError, UnicodeDecodeError, ValidationError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from exc

    user = _get_optional_user(request)
    valid_events: list[AnalyticsEventInput] = []
    errors: list[AnalyticsError] = []
    now = datetime.now(timezone.utc)
    for raw_event in envelope.events:
        event_id = raw_event.get("eventId", "") if isinstance(raw_event, dict) else ""
        try:
            event = AnalyticsEventInput.model_validate(raw_event)
        except ValidationError:
            errors.append(AnalyticsError(eventId=str(event_id), code="INVALID_EVENT"))
            continue
        code = validate_event_contract(event, now)
        if code:
            errors.append(AnalyticsError(eventId=str(event.eventId), code=code))
        else:
            valid_events.append(event)

    result = AnalyticsService().store_batch(valid_events, user.id if user else None)
    result.rejected += len(errors)
    combined_errors = errors + (result.errors or [])
    result.errors = combined_errors or None
    return result


def _get_optional_user(request: Request) -> User | None:
    access_token = request.cookies.get("access_token")
    if access_token is None:
        return None
    try:
        return AuthService().get_current_user(access_token)
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        ) from exc
