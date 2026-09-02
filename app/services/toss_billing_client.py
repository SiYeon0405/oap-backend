import base64
from dataclasses import dataclass, field
import re
from urllib.parse import quote

import httpx
from pydantic import SecretStr

from app.core.config import Settings, get_settings


BASE_URL = "https://api.tosspayments.com"
ISSUE_PATH = "/v1/billing/authorizations/issue"
CUSTOMER_KEY_PATTERN = re.compile(r"[A-Za-z0-9\-_=.@]{2,50}")


@dataclass(frozen=True)
class TossBillingKeyIssueResult:
    billing_key: str = field(repr=False)
    customer_key: str = field(repr=False)
    authenticated_at: str
    method: str
    card_issuer_code: str | None
    card_number_masked: str | None


class TossBillingConfigurationError(RuntimeError):
    pass


class TossBillingValidationError(ValueError):
    pass


class TossBillingTransportError(RuntimeError):
    pass


class TossBillingApiError(RuntimeError):
    def __init__(self, status_code: int, code: str):
        super().__init__("Toss billing API request failed")
        self.status_code = status_code
        self.code = code


class TossBillingResponseError(RuntimeError):
    pass


class TossBillingClient:
    __slots__ = ("_authorization", "_base_url", "_client", "_owns_client")

    def __init__(
        self,
        secret_key: SecretStr | str,
        *,
        base_url: str = BASE_URL,
        timeout_seconds: float = 30.0,
        http_client: httpx.Client | None = None,
    ):
        secret = (
            secret_key.get_secret_value()
            if isinstance(secret_key, SecretStr)
            else secret_key
        )
        if (
            not isinstance(secret, str)
            or not secret.strip()
            or not isinstance(base_url, str)
            or not base_url.strip()
            or timeout_seconds <= 0
        ):
            raise TossBillingConfigurationError(
                "Toss billing client is not configured"
            )
        try:
            encoded = base64.b64encode(f"{secret}:".encode("utf-8")).decode(
                "ascii"
            )
        except (TypeError, ValueError, UnicodeError):
            raise TossBillingConfigurationError(
                "Toss billing client is not configured"
            ) from None

        self._authorization = f"Basic {encoded}"
        self._base_url = base_url.rstrip("/")
        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(timeout=timeout_seconds)

    @classmethod
    def from_settings(
        cls,
        settings: Settings | None = None,
        **kwargs,
    ) -> "TossBillingClient":
        secret_key = getattr(settings or get_settings(), "toss_secret_key", None)
        if secret_key is None:
            raise TossBillingConfigurationError(
                "Toss billing client is not configured"
            )
        return cls(secret_key, **kwargs)

    def issue_billing_key(
        self,
        auth_key: str,
        customer_key: str,
    ) -> TossBillingKeyIssueResult:
        self._validate_input(auth_key, customer_key)
        try:
            response = self._client.post(
                self._base_url + ISSUE_PATH,
                headers={
                    "Authorization": self._authorization,
                    "Content-Type": "application/json",
                },
                json={"authKey": auth_key, "customerKey": customer_key},
            )
        except (httpx.TimeoutException, httpx.RequestError):
            raise TossBillingTransportError(
                "Toss billing transport failed"
            ) from None

        if not 200 <= response.status_code < 300:
            raise TossBillingApiError(
                response.status_code,
                self._safe_error_code(response),
            ) from None
        return self._parse_result(response, customer_key)

    def delete_billing_key(self, billing_key: str) -> None:
        if (
            not isinstance(billing_key, str)
            or not billing_key.strip()
            or billing_key != billing_key.strip()
            or len(billing_key) > 200
        ):
            raise TossBillingValidationError(
                "Toss billing request data is invalid"
            )
        try:
            response = self._client.delete(
                self._base_url + "/v1/billing/" + quote(billing_key, safe=""),
                headers={
                    "Authorization": self._authorization,
                    "Content-Type": "application/json",
                },
            )
        except (httpx.TimeoutException, httpx.RequestError):
            raise TossBillingTransportError(
                "Toss billing transport failed"
            ) from None

        if response.status_code != 200:
            raise TossBillingApiError(
                response.status_code,
                self._safe_error_code(response),
            ) from None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "TossBillingClient":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    @staticmethod
    def _validate_input(auth_key: str, customer_key: str) -> None:
        if (
            not isinstance(auth_key, str)
            or not auth_key.strip()
            or auth_key != auth_key.strip()
            or len(auth_key) > 300
            or not isinstance(customer_key, str)
            or customer_key != customer_key.strip()
            or CUSTOMER_KEY_PATTERN.fullmatch(customer_key) is None
        ):
            raise TossBillingValidationError(
                "Toss billing request data is invalid"
            )

    @staticmethod
    def _safe_error_code(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except (TypeError, ValueError):
            return "UNKNOWN_TOSS_ERROR"
        if isinstance(payload, dict) and isinstance(payload.get("code"), str):
            return payload["code"]
        return "UNKNOWN_TOSS_ERROR"

    @staticmethod
    def _parse_result(
        response: httpx.Response,
        requested_customer_key: str,
    ) -> TossBillingKeyIssueResult:
        try:
            payload = response.json()
        except (TypeError, ValueError):
            raise TossBillingResponseError(
                "Toss billing response is invalid"
            ) from None

        if not isinstance(payload, dict):
            raise TossBillingResponseError(
                "Toss billing response is invalid"
            )
        billing_key = payload.get("billingKey")
        customer_key = payload.get("customerKey")
        authenticated_at = payload.get("authenticatedAt")
        method = payload.get("method")
        card = payload.get("card")
        if (
            not isinstance(billing_key, str)
            or not billing_key.strip()
            or len(billing_key) > 200
            or customer_key != requested_customer_key
            or not isinstance(authenticated_at, str)
            or not authenticated_at.strip()
            or not isinstance(method, str)
            or not method.strip()
            or (card is not None and not isinstance(card, dict))
        ):
            raise TossBillingResponseError(
                "Toss billing response is invalid"
            )

        issuer_code = card.get("issuerCode") if isinstance(card, dict) else None
        card_number = card.get("number") if isinstance(card, dict) else None
        if (
            (issuer_code is not None and not isinstance(issuer_code, str))
            or (
                card_number is not None
                and (not isinstance(card_number, str) or len(card_number) > 20)
            )
        ):
            raise TossBillingResponseError(
                "Toss billing response is invalid"
            )
        return TossBillingKeyIssueResult(
            billing_key=billing_key,
            customer_key=customer_key,
            authenticated_at=authenticated_at,
            method=method,
            card_issuer_code=issuer_code,
            card_number_masked=card_number,
        )
