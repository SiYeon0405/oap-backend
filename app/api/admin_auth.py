import logging
from typing import Annotated, Callable
from uuid import uuid4

from fastapi import APIRouter, Cookie, Depends, Header, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from app.core.admin_permissions import role_has_permission
from app.core.config import get_admin_allowed_origins, get_settings
from app.models.admin import AdminUser
from app.schemas.admin_auth import (
    AdminAuthenticatedResponse,
    AdminLoginRequest,
    AdminLoginResponse,
    AdminLogoutResponse,
    AdminMeResponse,
    AdminMfaVerifyRequest,
    AdminRefreshResponse,
)
from app.services.admin_auth_service import (
    AdminAuthenticationError,
    AdminAuthService,
    AdminSessionExpiredError,
)
from app.services.admin_security import (
    ADMIN_ACCESS_COOKIE_NAME,
    ADMIN_CSRF_COOKIE_NAME,
    ADMIN_CSRF_HEADER_NAME,
    ADMIN_REFRESH_COOKIE_NAME,
    AdminSecurityConfigurationError,
    AdminTokenError,
    csrf_values_match,
    decode_admin_token,
    mask_ip_address,
)


logger = logging.getLogger(__name__)


class AdminApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message


class AdminAuthRoute(APIRoute):
    def get_route_handler(self) -> Callable:
        original = super().get_route_handler()

        async def handler(request: Request):
            request.state.admin_request_id = f"http_req_{uuid4().hex}"
            try:
                response = await original(request)
            except AdminApiError as exc:
                response = _error_response(request, exc.status_code, exc.code, exc.message)
            except RequestValidationError:
                response = _error_response(
                    request,
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    "ADMIN_AUTHENTICATION_FAILED",
                    "관리자 인증 요청이 올바르지 않습니다.",
                )
            except AdminSecurityConfigurationError:
                response = _error_response(
                    request,
                    status.HTTP_500_INTERNAL_SERVER_ERROR,
                    "ADMIN_CONFIGURATION_ERROR",
                    "관리자 인증 설정을 확인할 수 없습니다.",
                )
            except Exception:
                logger.error(
                    "Administrator authentication request failed: request_id=%s",
                    request.state.admin_request_id,
                )
                response = _error_response(
                    request,
                    status.HTTP_500_INTERNAL_SERVER_ERROR,
                    "ADMIN_AUTHENTICATION_FAILED",
                    "관리자 인증에 실패했습니다.",
                )
            _set_no_store(response)
            return response

        return handler


router = APIRouter(
    prefix="/api/v1/admin/auth",
    tags=["admin-auth"],
    route_class=AdminAuthRoute,
)


def require_admin_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin is None or origin == "null" or origin.rstrip("/") not in get_admin_allowed_origins():
        raise AdminApiError(
            status.HTTP_403_FORBIDDEN,
            "ADMIN_ORIGIN_DENIED",
            "허용되지 않은 관리자 요청입니다.",
        )


def require_admin_csrf(
    request: Request,
    csrf_cookie: Annotated[
        str | None, Cookie(alias=ADMIN_CSRF_COOKIE_NAME)
    ] = None,
    csrf_header: Annotated[
        str | None, Header(alias=ADMIN_CSRF_HEADER_NAME)
    ] = None,
    access_token: Annotated[
        str | None, Cookie(alias=ADMIN_ACCESS_COOKIE_NAME)
    ] = None,
) -> str:
    require_admin_origin(request)
    values = [csrf_cookie, csrf_header]
    if access_token:
        try:
            payload = decode_admin_token(access_token, "admin_access")
        except AdminTokenError:
            pass
        else:
            values.append(payload.get("csrf"))
    if not csrf_values_match(*values):
        raise AdminApiError(
            status.HTTP_403_FORBIDDEN,
            "ADMIN_CSRF_FAILED",
            "관리자 요청 검증에 실패했습니다.",
        )
    return csrf_cookie


def get_current_admin(
    access_token: Annotated[
        str | None, Cookie(alias=ADMIN_ACCESS_COOKIE_NAME)
    ] = None,
) -> AdminUser:
    if not access_token:
        raise _session_expired()
    try:
        return AdminAuthService().get_current_admin(access_token)
    except AdminSessionExpiredError as exc:
        raise _session_expired() from exc


def require_admin_permission(permission: str):
    def dependency(
        admin: Annotated[AdminUser, Depends(get_current_admin)],
    ) -> AdminUser:
        if not role_has_permission(admin.role, permission):
            raise AdminApiError(
                status.HTTP_403_FORBIDDEN,
                "ADMIN_PERMISSION_DENIED",
                "해당 정보를 조회할 권한이 없습니다.",
            )
        return admin

    return dependency


@router.post(
    "/login",
    response_model=AdminLoginResponse,
    dependencies=[Depends(require_admin_csrf)],
)
def login(payload: AdminLoginRequest, request: Request):
    try:
        result = AdminAuthService().login(
            payload.email,
            payload.password,
            request_id=request.state.admin_request_id,
            ip_address=_masked_client_ip(request),
        )
    except AdminAuthenticationError as exc:
        raise _authentication_failed() from exc
    return AdminLoginResponse(challengeId=result.challenge_id)


@router.post(
    "/mfa/verify",
    response_model=AdminAuthenticatedResponse,
    dependencies=[Depends(require_admin_csrf)],
)
def verify_mfa(payload: AdminMfaVerifyRequest, request: Request, response: Response):
    try:
        result = AdminAuthService().verify_mfa(
            payload.challengeId,
            payload.code,
            request_id=request.state.admin_request_id,
            ip_address=_masked_client_ip(request),
        )
    except AdminAuthenticationError as exc:
        raise _authentication_failed() from exc
    _set_admin_cookies(response, result.access_token, result.refresh_token, result.csrf_token)
    return AdminAuthenticatedResponse()


@router.get("/me", response_model=AdminMeResponse)
def me(admin: Annotated[AdminUser, Depends(get_current_admin)]):
    from app.core.admin_permissions import permissions_for_role

    return AdminMeResponse(
        id=admin.id,
        email=admin.email,
        name=admin.name,
        role=admin.role,
        permissions=sorted(permissions_for_role(admin.role)),
    )


@router.post(
    "/refresh",
    response_model=AdminRefreshResponse,
    dependencies=[Depends(require_admin_origin)],
)
def refresh(
    request: Request,
    refresh_token: Annotated[
        str | None, Cookie(alias=ADMIN_REFRESH_COOKIE_NAME)
    ] = None,
    csrf_token: Annotated[str, Depends(require_admin_csrf)] = None,
):
    if not refresh_token:
        raise _session_expired()
    try:
        result = AdminAuthService().refresh(
            refresh_token,
            csrf_token,
            request_id=request.state.admin_request_id,
            ip_address=_masked_client_ip(request),
        )
    except AdminSessionExpiredError:
        response = _error_response(
            request,
            status.HTTP_401_UNAUTHORIZED,
            "ADMIN_SESSION_EXPIRED",
            "관리자 세션이 만료되었습니다.",
        )
        _clear_admin_cookies(response)
        return response
    response = JSONResponse(AdminRefreshResponse().model_dump())
    _set_admin_cookies(response, result.access_token, result.refresh_token, result.csrf_token)
    return response


@router.post(
    "/logout",
    response_model=AdminLogoutResponse,
    dependencies=[Depends(require_admin_csrf)],
)
def logout(
    request: Request,
    response: Response,
    access_token: Annotated[
        str | None, Cookie(alias=ADMIN_ACCESS_COOKIE_NAME)
    ] = None,
    refresh_token: Annotated[
        str | None, Cookie(alias=ADMIN_REFRESH_COOKIE_NAME)
    ] = None,
):
    AdminAuthService().logout(
        access_token,
        refresh_token,
        request_id=request.state.admin_request_id,
        ip_address=_masked_client_ip(request),
    )
    _clear_admin_cookies(response)
    return AdminLogoutResponse()


def _authentication_failed() -> AdminApiError:
    return AdminApiError(
        status.HTTP_401_UNAUTHORIZED,
        "ADMIN_AUTHENTICATION_FAILED",
        "관리자 인증에 실패했습니다.",
    )


def _session_expired() -> AdminApiError:
    return AdminApiError(
        status.HTTP_401_UNAUTHORIZED,
        "ADMIN_SESSION_EXPIRED",
        "관리자 세션이 만료되었습니다.",
    )


def _error_response(
    request: Request, status_code: int, code: str, message: str
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "requestId": request.state.admin_request_id,
            }
        },
    )


def _set_no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"


def _set_admin_cookies(
    response: Response, access_token: str, refresh_token: str, csrf_token: str
) -> None:
    settings = get_settings()
    common = {
        "secure": settings.admin_cookie_secure,
        "samesite": settings.admin_cookie_samesite,
        "domain": settings.admin_cookie_domain,
    }
    response.set_cookie(
        ADMIN_ACCESS_COOKIE_NAME,
        access_token,
        httponly=True,
        path="/api/v1/admin",
        max_age=settings.admin_access_token_expire_minutes * 60,
        **common,
    )
    response.set_cookie(
        ADMIN_REFRESH_COOKIE_NAME,
        refresh_token,
        httponly=True,
        path="/api/v1/admin/auth",
        max_age=settings.admin_refresh_token_expire_days * 86400,
        **common,
    )
    response.set_cookie(
        ADMIN_CSRF_COOKIE_NAME,
        csrf_token,
        httponly=False,
        path="/api/v1/admin",
        max_age=settings.admin_refresh_token_expire_days * 86400,
        **common,
    )


def _clear_admin_cookies(response: Response) -> None:
    settings = get_settings()
    common = {
        "secure": settings.admin_cookie_secure,
        "samesite": settings.admin_cookie_samesite,
        "domain": settings.admin_cookie_domain,
    }
    response.delete_cookie(
        ADMIN_ACCESS_COOKIE_NAME,
        path="/api/v1/admin",
        httponly=True,
        **common,
    )
    response.delete_cookie(
        ADMIN_REFRESH_COOKIE_NAME,
        path="/api/v1/admin/auth",
        httponly=True,
        **common,
    )
    response.delete_cookie(
        ADMIN_CSRF_COOKIE_NAME,
        path="/api/v1/admin",
        httponly=False,
        **common,
    )


def _masked_client_ip(request: Request) -> str | None:
    return mask_ip_address(request.client.host if request.client else None)
