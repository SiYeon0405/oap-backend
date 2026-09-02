import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import billing
from app.api.auth import get_current_user
from app.services.billing_security import BillingSecurityConfigurationError
from app.services.billing_service import (
    BillingCompensationError,
    BillingPersistenceError,
    BillingProviderError,
    BillingRegistrationExpiredOrUsedError,
    BillingRegistrationUnavailableError,
    BillingServiceError,
    BillingUserUnavailableError,
)
from app.services.toss_billing_client import TossBillingConfigurationError


FAKE_USER_ID = 17
FAKE_CUSTOMER_KEY = "11111111-2222-4333-8444-555555555555"
FAKE_AUTH_KEY = "TEST_AUTH_VALUE"


class BillingApiTest(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(billing.router)
        self.service = Mock()
        self.app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=FAKE_USER_ID
        )
        self.app.dependency_overrides[billing.get_billing_service] = (
            lambda: self.service
        )
        self.client = TestClient(self.app)

    def tearDown(self):
        self.app.dependency_overrides.clear()
        self.client.close()

    def assert_no_cache(self, response):
        self.assertEqual(response.headers.get("cache-control"), "no-store")
        self.assertEqual(response.headers.get("pragma"), "no-cache")

    def assert_safe_error(self, response, status_code, code):
        self.assertEqual(response.status_code, status_code)
        detail = response.json()["detail"]
        self.assertEqual(detail["code"], code)
        self.assertIsInstance(detail["message"], str)
        self.assertTrue(detail["message"])
        rendered = response.text
        self.assertNotIn(FAKE_AUTH_KEY, rendered)
        self.assertNotIn(FAKE_CUSTOMER_KEY, rendered)

    def complete_payload(self, **overrides):
        payload = {"authKey": FAKE_AUTH_KEY, "customerKey": FAKE_CUSTOMER_KEY}
        payload.update(overrides)
        return payload

    def complete_result(self, cleanup_required=False):
        return SimpleNamespace(
            billing_method_id=41,
            card_issuer_code="TEST",
            card_number_masked="1234****5678",
            authenticated_at="2026-09-02T12:00:00+00:00",
            cleanup_required=cleanup_required,
        )

    def test_start_registration_returns_201(self):
        expires_at = datetime(2026, 9, 2, 12, 15, tzinfo=timezone.utc)
        self.service.start_registration.return_value = SimpleNamespace(
            customer_key=FAKE_CUSTOMER_KEY,
            expires_at=expires_at,
        )

        response = self.client.post("/api/v1/billing/registration/start")

        self.assertEqual(response.status_code, 201)
        self.service.start_registration.assert_called_once_with(FAKE_USER_ID)
        self.assertEqual(
            set(response.json()),
            {"customerKey", "expiresAt"},
        )
        self.assertEqual(response.json()["customerKey"], FAKE_CUSTOMER_KEY)
        for forbidden in ("userId", "billingKey", "authKey"):
            self.assertNotIn(forbidden, response.json())
        self.assert_no_cache(response)
        self.service.complete_registration.assert_not_called()

    def test_complete_registration_returns_200(self):
        self.service.complete_registration.return_value = self.complete_result()

        response = self.client.post(
            "/api/v1/billing/registration/complete",
            json=self.complete_payload(),
        )

        self.assertEqual(response.status_code, 200)
        self.service.complete_registration.assert_called_once_with(
            FAKE_USER_ID,
            FAKE_CUSTOMER_KEY,
            FAKE_AUTH_KEY,
        )
        self.assertEqual(
            set(response.json()),
            {
                "billingMethodId",
                "cardIssuerCode",
                "cardNumberMasked",
                "authenticatedAt",
                "cleanupRequired",
            },
        )
        for forbidden in (
            "authKey",
            "customerKey",
            "billingKey",
            "billingKeyEncrypted",
            "userId",
        ):
            self.assertNotIn(forbidden, response.json())
        self.assert_no_cache(response)

    def test_complete_registration_returns_success_when_cleanup_required(self):
        self.service.complete_registration.return_value = self.complete_result(True)

        response = self.client.post(
            "/api/v1/billing/registration/complete",
            json=self.complete_payload(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIs(response.json()["cleanupRequired"], True)

    def test_complete_registration_rejects_invalid_request(self):
        invalid_payloads = (
            self.complete_payload(authKey=""),
            self.complete_payload(authKey=" PADDED"),
            self.complete_payload(customerKey="INVALID VALUE"),
            self.complete_payload(customerKey=" PADDED"),
        )
        for payload in invalid_payloads:
            with self.subTest(case=tuple(payload)):
                self.service.complete_registration.reset_mock()
                response = self.client.post(
                    "/api/v1/billing/registration/complete",
                    json=payload,
                )
                self.assertEqual(response.status_code, 422)
                self.service.complete_registration.assert_not_called()

        self.service.complete_registration.return_value = self.complete_result()
        response = self.client.post(
            "/api/v1/billing/registration/complete",
            json={**self.complete_payload(), "userId": 999},
        )
        self.assertEqual(response.status_code, 200)
        self.service.complete_registration.assert_called_once_with(
            FAKE_USER_ID,
            FAKE_CUSTOMER_KEY,
            FAKE_AUTH_KEY,
        )
        self.assertNotIn("userId", response.json())

    def test_start_registration_exception_mapping(self):
        cases = (
            (BillingUserUnavailableError(), 403, "BILLING_USER_UNAVAILABLE"),
            (
                BillingPersistenceError(),
                503,
                "BILLING_TEMPORARILY_UNAVAILABLE",
            ),
            (BillingServiceError(), 500, "BILLING_INTERNAL_ERROR"),
        )
        for error, status_code, code in cases:
            with self.subTest(error=type(error).__name__):
                self.service.start_registration.side_effect = error
                response = self.client.post("/api/v1/billing/registration/start")
                self.assert_safe_error(response, status_code, code)
                self.assert_no_cache(response)

    def test_complete_registration_exception_mapping(self):
        cases = (
            (
                BillingRegistrationUnavailableError(),
                400,
                "BILLING_REGISTRATION_INVALID",
            ),
            (BillingUserUnavailableError(), 403, "BILLING_USER_UNAVAILABLE"),
            (
                BillingRegistrationExpiredOrUsedError(),
                409,
                "BILLING_REGISTRATION_EXPIRED_OR_USED",
            ),
            (BillingProviderError(), 502, "BILLING_PROVIDER_ERROR"),
            (
                BillingPersistenceError(),
                503,
                "BILLING_TEMPORARILY_UNAVAILABLE",
            ),
            (BillingCompensationError(), 503, "BILLING_REQUIRES_ATTENTION"),
            (BillingServiceError(), 500, "BILLING_INTERNAL_ERROR"),
        )
        for error, status_code, code in cases:
            with self.subTest(error=type(error).__name__):
                self.service.complete_registration.side_effect = error
                response = self.client.post(
                    "/api/v1/billing/registration/complete",
                    json=self.complete_payload(),
                )
                self.assert_safe_error(response, status_code, code)
                self.assert_no_cache(response)

    def test_service_configuration_error_returns_503(self):
        self.app.dependency_overrides.pop(billing.get_billing_service)
        for error_type in (
            TossBillingConfigurationError,
            BillingSecurityConfigurationError,
        ):
            with self.subTest(error=error_type.__name__), patch.object(
                billing,
                "BillingService",
                side_effect=error_type(),
            ) as constructor:
                response = self.client.post("/api/v1/billing/registration/start")
                self.assert_safe_error(
                    response,
                    503,
                    "BILLING_TEMPORARILY_UNAVAILABLE",
                )
                constructor.assert_called_once_with()

    def test_routes_include_required_dependencies(self):
        for route in billing.router.routes:
            with self.subTest(path=route.path):
                dependency_calls = {
                    dependency.call for dependency in route.dependant.dependencies
                }
                self.assertIn(get_current_user, dependency_calls)
                self.assertIn(billing.get_billing_service, dependency_calls)

    def test_openapi_and_route_contract(self):
        paths = self.app.openapi()["paths"]
        start = paths["/api/v1/billing/registration/start"]
        complete = paths["/api/v1/billing/registration/complete"]

        self.assertEqual(set(start), {"post"})
        self.assertEqual(set(complete), {"post"})
        self.assertIn("201", start["post"]["responses"])
        self.assertIn("200", complete["post"]["responses"])
        schemas = self.app.openapi()["components"]["schemas"]
        request_contract = str(schemas["BillingRegistrationCompleteRequest"])
        response_contract = str(schemas["BillingRegistrationCompleteResponse"])
        self.assertNotIn("userId", request_contract)
        self.assertNotIn("billingKey", response_contract)
        self.assertEqual(len(billing.router.routes), 2)


if __name__ == "__main__":
    unittest.main()
