from typing import Annotated, Iterator

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.auth import get_current_user
from app.models.user import User
from app.schemas.billing import (
    BillingRegistrationCompleteRequest,
    BillingRegistrationCompleteResponse,
    BillingRegistrationStartResponse,
)
from app.services.billing_security import BillingSecurityConfigurationError
from app.services.billing_service import (
    BillingCompensationError,
    BillingPersistenceError,
    BillingProviderError,
    BillingRegistrationExpiredOrUsedError,
    BillingRegistrationUnavailableError,
    BillingService,
    BillingServiceError,
    BillingUserUnavailableError,
)
from app.services.toss_billing_client import TossBillingConfigurationError

router = APIRouter(prefix="/api/v1/billing", tags=["billing"])


def _http_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


def get_billing_service() -> Iterator[BillingService]:
    try:
        service = BillingService()
    except (TossBillingConfigurationError, BillingSecurityConfigurationError):
        raise _http_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "BILLING_TEMPORARILY_UNAVAILABLE",
            "Billing is temporarily unavailable",
        ) from None

    try:
        yield service
    finally:
        service.close()


def _disable_cache(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


@router.post(
    "/registration/start",
    response_model=BillingRegistrationStartResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start billing registration",
)
def start_billing_registration(
    response: Response,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[BillingService, Depends(get_billing_service)],
) -> BillingRegistrationStartResponse:
    _disable_cache(response)
    try:
        result = service.start_registration(user.id)
    except BillingUserUnavailableError:
        raise _http_error(
            status.HTTP_403_FORBIDDEN,
            "BILLING_USER_UNAVAILABLE",
            "Billing is unavailable for this user",
        ) from None
    except BillingPersistenceError:
        raise _http_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "BILLING_TEMPORARILY_UNAVAILABLE",
            "Billing is temporarily unavailable",
        ) from None
    except BillingServiceError:
        raise _http_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "BILLING_INTERNAL_ERROR",
            "Billing request could not be processed",
        ) from None

    return BillingRegistrationStartResponse(
        customer_key=result.customer_key,
        expires_at=result.expires_at,
    )


@router.post(
    "/registration/complete",
    response_model=BillingRegistrationCompleteResponse,
    status_code=status.HTTP_200_OK,
    summary="Complete billing registration",
)
def complete_billing_registration(
    request: BillingRegistrationCompleteRequest,
    response: Response,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[BillingService, Depends(get_billing_service)],
) -> BillingRegistrationCompleteResponse:
    _disable_cache(response)
    try:
        result = service.complete_registration(
            user.id,
            request.customer_key,
            request.auth_key,
        )
    except BillingUserUnavailableError:
        raise _http_error(
            status.HTTP_403_FORBIDDEN,
            "BILLING_USER_UNAVAILABLE",
            "Billing is unavailable for this user",
        ) from None
    except BillingRegistrationUnavailableError:
        raise _http_error(
            status.HTTP_400_BAD_REQUEST,
            "BILLING_REGISTRATION_INVALID",
            "Billing registration is invalid",
        ) from None
    except BillingRegistrationExpiredOrUsedError:
        raise _http_error(
            status.HTTP_409_CONFLICT,
            "BILLING_REGISTRATION_EXPIRED_OR_USED",
            "Billing registration is expired or already used",
        ) from None
    except BillingProviderError:
        raise _http_error(
            status.HTTP_502_BAD_GATEWAY,
            "BILLING_PROVIDER_ERROR",
            "Billing provider request failed",
        ) from None
    except BillingCompensationError:
        raise _http_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "BILLING_REQUIRES_ATTENTION",
            "Billing request requires attention",
        ) from None
    except BillingPersistenceError:
        raise _http_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "BILLING_TEMPORARILY_UNAVAILABLE",
            "Billing is temporarily unavailable",
        ) from None
    except BillingServiceError:
        raise _http_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "BILLING_INTERNAL_ERROR",
            "Billing request could not be processed",
        ) from None

    return BillingRegistrationCompleteResponse(
        billing_method_id=result.billing_method_id,
        card_issuer_code=result.card_issuer_code,
        card_number_masked=result.card_number_masked,
        authenticated_at=result.authenticated_at,
        cleanup_required=result.cleanup_required,
    )
