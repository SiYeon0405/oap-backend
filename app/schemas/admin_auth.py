import re
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AdminLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=72)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not EMAIL_PATTERN.fullmatch(normalized):
            raise ValueError("Invalid email format")
        return normalized

    @field_validator("password")
    @classmethod
    def validate_password_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password is too long")
        return value


class AdminMfaVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    challengeId: UUID
    code: str = Field(pattern=r"^\d{6}$")


class AdminLoginResponse(BaseModel):
    mfaRequired: bool = True
    challengeId: UUID
    expiresInSeconds: int = 300


class AdminAuthenticatedResponse(BaseModel):
    authenticated: bool = True


class AdminMeResponse(BaseModel):
    id: int
    email: str
    name: str
    role: str
    permissions: list[str]


class AdminRefreshResponse(BaseModel):
    refreshed: bool = True


class AdminLogoutResponse(BaseModel):
    loggedOut: bool = True
