import os
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status

from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    SignupRequest,
    SignupResponse,
)
from app.services.auth_service import (
    AuthService,
    EmailAlreadyExistsError,
    InvalidCredentialsError,
)


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


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


@router.post(
    "/signup",
    response_model=SignupResponse,
    status_code=status.HTTP_201_CREATED,
)
def signup(request: SignupRequest):
    try:
        user = AuthService().signup(request)
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

    cookie_secure = _get_bool_env("COOKIE_SECURE", default=True)
    cookie_samesite = os.getenv("COOKIE_SAMESITE", "none").lower()
    if cookie_samesite not in {"lax", "strict", "none"}:
        raise RuntimeError("COOKIE_SAMESITE must be lax, strict, or none")

    response.set_cookie(
        key="access_token",
        value=result.access_token,
        httponly=True,
        secure=cookie_secure,
        samesite=cookie_samesite,
        path="/",
        max_age=_get_positive_int_env("JWT_ACCESS_EXPIRE_MINUTES") * 60,
    )
    response.set_cookie(
        key="refresh_token",
        value=result.refresh_token,
        httponly=True,
        secure=cookie_secure,
        samesite=cookie_samesite,
        path="/api/v1/auth",
        max_age=_get_positive_int_env("JWT_REFRESH_EXPIRE_DAYS") * 24 * 60 * 60,
    )
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


def _get_bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.lower()
    if normalized not in {"true", "false"}:
        raise RuntimeError(f"{name} must be true or false")
    return normalized == "true"


def _get_positive_int_env(name: str) -> int:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is not configured")
    try:
        parsed_value = int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if parsed_value <= 0:
        raise RuntimeError(f"{name} must be positive")
    return parsed_value
