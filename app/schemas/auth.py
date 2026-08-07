import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SignupRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=72)
    name: str = Field(min_length=1, max_length=100)
    termsAgreed: bool
    privacyAgreed: bool
    marketingAgreed: bool = False

    @model_validator(mode="after")
    def validate_required_consents(self):
        if not self.termsAgreed:
            raise ValueError("Terms consent is required")
        if not self.privacyAgreed:
            raise ValueError("Privacy consent is required")
        return self

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not EMAIL_PATTERN.fullmatch(normalized):
            raise ValueError("Invalid email format")
        return normalized

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must not exceed 72 bytes")
        return value

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Name must not be blank")
        return normalized


class SignupResponse(BaseModel):
    id: int
    email: str
    name: str | None
    status: str
    createdAt: datetime


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=72)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not EMAIL_PATTERN.fullmatch(normalized):
            raise ValueError("Invalid email format")
        return normalized

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must not exceed 72 bytes")
        return value


class GoogleLoginRequest(BaseModel):
    idToken: str = Field(min_length=1)
    termsAgreed: bool
    privacyAgreed: bool
    marketingAgreed: bool = False

    @model_validator(mode="after")
    def validate_required_consents(self):
        if not self.termsAgreed:
            raise ValueError("Terms consent is required")
        if not self.privacyAgreed:
            raise ValueError("Privacy consent is required")
        return self


class LoginResponse(BaseModel):
    id: int
    email: str
    name: str | None
    status: str


class DeleteAccountRequest(BaseModel):
    password: str | None = Field(default=None, min_length=1, max_length=72)
    idToken: str | None = Field(default=None, min_length=1)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must not exceed 72 bytes")
        return value


class AuthActionResponse(BaseModel):
    detail: str


ConsentType = Literal["TERMS", "PRIVACY", "MARKETING"]


class ConsentItem(BaseModel):
    type: ConsentType
    documentVersion: str
    agreed: bool
    occurredAt: datetime


class ConsentResponse(BaseModel):
    current: list[ConsentItem]
    history: list[ConsentItem]


class MarketingConsentRequest(BaseModel):
    agreed: bool
