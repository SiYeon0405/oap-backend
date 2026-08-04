import os
from dataclasses import dataclass
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    Header,
    HTTPException,
    Request,
    Response,
    status,
)

from app.models.user import User
from app.schemas.auth import (
    AuthActionResponse,
    ConsentItem,
    ConsentResponse,
    DeleteAccountRequest,
    LoginRequest,
    LoginResponse,
    MarketingConsentRequest,
    SignupRequest,
    SignupResponse,
)
from app.services.user_consent_service import UserConsentService
from app.services.auth_service import (
    AccountDeletionError,
    AuthService,
    EmailAlreadyExistsError,
    InvalidCredentialsError,
)


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
ALLOWED_ORIGINS = {
    "http://localhost:3000",
    "http://localhost:3001",
    "http://localhost:5173",
}


@dataclass(frozen=True)
class CookieSettings:
    secure: bool
    samesite: str
    domain: str | None


def get_current_user(
    access_token: Annotated[str | None, Cookie()] = None,
) -> User:
    if access_token is None:
        raise _unauthorized()
    try:
        return AuthService().get_current_user(access_token)
    except InvalidCredentialsError as exc:
        raise _unauthorized() from exc


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
    )


def validate_request_origin(
    origin: Annotated[str | None, Header()] = None,
    referer: Annotated[str | None, Header()] = None,
) -> None:
    request_origin = origin
    if request_origin is None and referer:
        parsed = urlsplit(referer)
        request_origin = f"{parsed.scheme}://{parsed.netloc}"
    if request_origin is not None and request_origin not in ALLOWED_ORIGINS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Origin not allowed",
        )


@router.post(
    "/signup",
    response_model=SignupResponse,
    status_code=status.HTTP_201_CREATED,
)
def signup(request: SignupRequest, http_request: Request):
    try:
        user = AuthService().signup(
            request,
            ip_address=_client_ip(http_request),
            user_agent=http_request.headers.get("user-agent"),
        )
    except EmailAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already exists",
        ) from exc

    return SignupResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        status=user.status,
        createdAt=user.created_at,
    )


@router.get(
    "/consents",
    response_model=ConsentResponse,
    status_code=status.HTTP_200_OK,
)
def get_consents(user: Annotated[User, Depends(get_current_user)]):
    return UserConsentService().get_consents(user.id)


@router.patch(
    "/consents/marketing",
    response_model=ConsentItem,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(validate_request_origin)],
)
def update_marketing_consent(
    request: MarketingConsentRequest,
    http_request: Request,
    user: Annotated[User, Depends(get_current_user)],
):
    return UserConsentService().set_marketing(
        user.id,
        request.agreed,
        ip_address=_client_ip(http_request),
        user_agent=http_request.headers.get("user-agent"),
    )


@router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
)
def login(request: LoginRequest, response: Response):
    try:
        result = AuthService().login(request)
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        ) from exc

    _set_auth_cookies(response, result.access_token, result.refresh_token)
    return LoginResponse(
        id=result.user.id,
        email=result.user.email,
        name=result.user.name,
        status=result.user.status,
    )


@router.get(
    "/me",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
)
def me(user: Annotated[User, Depends(get_current_user)]):
    return LoginResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        status=user.status,
    )


@router.post(
    "/refresh",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(validate_request_origin)],
)
def refresh(
    response: Response,
    refresh_token: Annotated[str | None, Cookie()] = None,
):
    if refresh_token is None:
        raise _unauthorized()
    try:
        result = AuthService().refresh(refresh_token)
    except InvalidCredentialsError as exc:
        raise _unauthorized() from exc

    _set_auth_cookies(response, result.access_token, result.refresh_token)
    return LoginResponse(
        id=result.user.id,
        email=result.user.email,
        name=result.user.name,
        status=result.user.status,
    )


@router.post(
    "/logout",
    response_model=AuthActionResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(validate_request_origin)],
)
def logout(
    response: Response,
    refresh_token: Annotated[str | None, Cookie()] = None,
):
    AuthService().logout(refresh_token)
    _clear_auth_cookies(response)
    return AuthActionResponse(detail="Logged out")


@router.delete(
    "/me",
    response_model=AuthActionResponse,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(validate_request_origin)],
)
def delete_me(
    request: DeleteAccountRequest,
    response: Response,
    user: Annotated[User, Depends(get_current_user)],
):
    try:
        AuthService().delete_account(user.id, request)
    except AccountDeletionError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid password",
        ) from exc
    _clear_auth_cookies(response)
    return AuthActionResponse(detail="Account deleted")


def _set_auth_cookies(
    response: Response,
    access_token: str,
    refresh_token: str,
) -> None:
    settings = _get_cookie_settings()
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=settings.secure,
        samesite=settings.samesite,
        domain=settings.domain,
        path="/",
        max_age=AuthService.get_access_expire_minutes() * 60,
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=settings.secure,
        samesite=settings.samesite,
        domain=settings.domain,
        path="/api/v1/auth",
        max_age=AuthService.get_refresh_expire_days() * 24 * 60 * 60,
    )


def _clear_auth_cookies(response: Response) -> None:
    settings = _get_cookie_settings()
    response.delete_cookie(
        key="access_token",
        path="/",
        domain=settings.domain,
        secure=settings.secure,
        httponly=True,
        samesite=settings.samesite,
    )
    response.delete_cookie(
        key="refresh_token",
        path="/api/v1/auth",
        domain=settings.domain,
        secure=settings.secure,
        httponly=True,
        samesite=settings.samesite,
    )


def _get_cookie_settings() -> CookieSettings:
    cookie_samesite = os.getenv("COOKIE_SAMESITE", "none").lower()
    if cookie_samesite not in {"lax", "strict", "none"}:
        raise RuntimeError("COOKIE_SAMESITE must be lax, strict, or none")
    cookie_domain = os.getenv("COOKIE_DOMAIN")
    return CookieSettings(
        secure=_get_bool_env("COOKIE_SECURE", default=True),
        samesite=cookie_samesite,
        domain=cookie_domain if cookie_domain and cookie_domain.strip() else None,
    )


def _get_bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.lower()
    if normalized not in {"true", "false"}:
        raise RuntimeError(f"{name} must be true or false")
    return normalized == "true"


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client is not None else None
