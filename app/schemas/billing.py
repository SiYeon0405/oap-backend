from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


CUSTOMER_KEY_PATTERN = r"^[A-Za-z0-9\-_=.@]{2,50}$"


def _require_timezone(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Datetime must include a timezone")
    return value


class BillingRegistrationStartResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    customer_key: str = Field(
        alias="customerKey",
        min_length=2,
        max_length=50,
        pattern=CUSTOMER_KEY_PATTERN,
    )
    expires_at: datetime = Field(alias="expiresAt")

    @field_validator("expires_at")
    @classmethod
    def validate_expires_at(cls, value: datetime) -> datetime:
        return _require_timezone(value)


class BillingRegistrationCompleteRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    auth_key: str = Field(alias="authKey", min_length=1, max_length=300)
    customer_key: str = Field(
        alias="customerKey",
        min_length=2,
        max_length=50,
        pattern=CUSTOMER_KEY_PATTERN,
    )

    @field_validator("auth_key")
    @classmethod
    def validate_auth_key(cls, value: str) -> str:
        if not value.strip() or value != value.strip():
            raise ValueError("Auth key must not be blank or padded")
        return value


class BillingRegistrationCompleteResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    billing_method_id: int = Field(alias="billingMethodId", gt=0)
    card_issuer_code: str | None = Field(
        default=None,
        alias="cardIssuerCode",
        max_length=10,
    )
    card_number_masked: str | None = Field(
        default=None,
        alias="cardNumberMasked",
        max_length=20,
    )
    authenticated_at: datetime = Field(alias="authenticatedAt")
    cleanup_required: bool = Field(alias="cleanupRequired")

    @field_validator("authenticated_at")
    @classmethod
    def validate_authenticated_at(cls, value: datetime) -> datetime:
        return _require_timezone(value)
