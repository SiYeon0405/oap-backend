import base64
import hmac
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
from pydantic import SecretStr

from app.services.toss_billing_client import (
    TossBillingApiError,
    TossBillingClient,
    TossBillingConfigurationError,
    TossBillingResponseError,
    TossBillingTransportError,
    TossBillingValidationError,
)


TEST_SECRET_VALUE = "TEST_SECRET_VALUE"
TEST_AUTH_VALUE = "TEST_AUTH_VALUE"
TEST_CUSTOMER_VALUE = "TEST_CUSTOMER_VALUE"
TEST_BILLING_VALUE = "TEST_BILLING_VALUE"
TEST_PROVIDER_MESSAGE = "TEST_SENSITIVE_PROVIDER_MESSAGE"


class TossBillingClientTest(unittest.TestCase):
    def make_client(self, handler):
        calls = []

        def tracked_handler(request):
            calls.append(request.method)
            return handler(request)

        http_client = httpx.Client(transport=httpx.MockTransport(tracked_handler))
        self.addCleanup(http_client.close)
        return (
            TossBillingClient(
                SecretStr(TEST_SECRET_VALUE),
                http_client=http_client,
            ),
            calls,
        )

    @staticmethod
    def success_payload(**overrides):
        payload = {
            "billingKey": TEST_BILLING_VALUE,
            "customerKey": TEST_CUSTOMER_VALUE,
            "authenticatedAt": "TEST_AUTHENTICATED_AT",
            "method": "TEST_METHOD",
            "card": {
                "issuerCode": "TEST_ISSUER",
                "number": "MASKED_TEST_VALUE",
            },
        }
        payload.update(overrides)
        return payload

    def assert_safe(self, value):
        rendered = f"{value!s} {value!r}"
        for sensitive in (
            TEST_SECRET_VALUE,
            TEST_AUTH_VALUE,
            TEST_CUSTOMER_VALUE,
            TEST_BILLING_VALUE,
            TEST_PROVIDER_MESSAGE,
        ):
            self.assertNotIn(sensitive, rendered)

    def test_issue_billing_key_sends_expected_request(self):
        def handler(request):
            self.assertEqual(request.method, "POST")
            self.assertEqual(request.url.path, "/v1/billing/authorizations/issue")
            self.assertEqual(request.headers.get("content-type"), "application/json")
            authorization = request.headers.get("authorization", "")
            scheme, encoded = authorization.split(" ", 1)
            self.assertEqual(scheme, "Basic")
            decoded = base64.b64decode(encoded).decode("utf-8")
            self.assertTrue(
                hmac.compare_digest(decoded, TEST_SECRET_VALUE + ":")
            )
            payload = json.loads(request.content.decode("utf-8"))
            self.assertTrue(
                hmac.compare_digest(payload.get("authKey", ""), TEST_AUTH_VALUE)
            )
            self.assertTrue(
                hmac.compare_digest(
                    payload.get("customerKey", ""),
                    TEST_CUSTOMER_VALUE,
                )
            )
            return httpx.Response(200, json=self.success_payload())

        client, calls = self.make_client(handler)
        result = client.issue_billing_key(TEST_AUTH_VALUE, TEST_CUSTOMER_VALUE)

        self.assertEqual(calls, ["POST"])
        self.assertEqual(result.billing_key, TEST_BILLING_VALUE)
        self.assertEqual(result.customer_key, TEST_CUSTOMER_VALUE)
        self.assertEqual(result.authenticated_at, "TEST_AUTHENTICATED_AT")
        self.assertEqual(result.method, "TEST_METHOD")
        self.assertEqual(result.card_issuer_code, "TEST_ISSUER")
        self.assertEqual(result.card_number_masked, "MASKED_TEST_VALUE")
        self.assertNotIn(TEST_BILLING_VALUE, repr(result))
        self.assertNotIn(TEST_CUSTOMER_VALUE, repr(result))

    def test_issue_billing_key_accepts_null_card(self):
        client, _ = self.make_client(
            lambda request: httpx.Response(
                200,
                json=self.success_payload(card=None),
            )
        )
        result = client.issue_billing_key(TEST_AUTH_VALUE, TEST_CUSTOMER_VALUE)
        self.assertIsNone(result.card_issuer_code)
        self.assertIsNone(result.card_number_masked)

    def test_issue_billing_key_rejects_invalid_input(self):
        invalid_values = (
            ("", TEST_CUSTOMER_VALUE),
            (" TEST_AUTH_VALUE", TEST_CUSTOMER_VALUE),
            ("A" * 301, TEST_CUSTOMER_VALUE),
            (TEST_AUTH_VALUE, ""),
            (TEST_AUTH_VALUE, "A"),
            (TEST_AUTH_VALUE, "A" * 51),
            (TEST_AUTH_VALUE, "INVALID/VALUE"),
            (TEST_AUTH_VALUE, " TEST_CUSTOMER_VALUE"),
        )
        for auth_key, customer_key in invalid_values:
            with self.subTest(case=len(auth_key) + len(customer_key)):
                client, calls = self.make_client(
                    lambda request: self.fail("transport must not be called")
                )
                with self.assertRaises(TossBillingValidationError) as caught:
                    client.issue_billing_key(auth_key, customer_key)
                self.assertEqual(calls, [])
                self.assert_safe(caught.exception)

    def test_issue_billing_key_rejects_customer_key_mismatch(self):
        client, _ = self.make_client(
            lambda request: httpx.Response(
                200,
                json=self.success_payload(customerKey="TEST_OTHER_CUSTOMER"),
            )
        )
        with self.assertRaises(TossBillingResponseError) as caught:
            client.issue_billing_key(TEST_AUTH_VALUE, TEST_CUSTOMER_VALUE)
        self.assert_safe(caught.exception)
        self.assertNotIn("TEST_OTHER_CUSTOMER", str(caught.exception))

    def test_issue_billing_key_rejects_invalid_success_response(self):
        cases = (
            ["NOT_AN_OBJECT"],
            {key: value for key, value in self.success_payload().items() if key != "billingKey"},
            self.success_payload(billingKey=""),
            self.success_payload(billingKey="B" * 201),
            {key: value for key, value in self.success_payload().items() if key != "authenticatedAt"},
            {key: value for key, value in self.success_payload().items() if key != "method"},
            self.success_payload(card="NOT_AN_OBJECT"),
            self.success_payload(card={"issuerCode": 1, "number": None}),
            self.success_payload(card={"issuerCode": None, "number": 1}),
            self.success_payload(card={"issuerCode": None, "number": "N" * 21}),
        )
        for index, payload in enumerate(cases):
            with self.subTest(case=index):
                client, _ = self.make_client(
                    lambda request, payload=payload: httpx.Response(200, json=payload)
                )
                with self.assertRaises(TossBillingResponseError) as caught:
                    client.issue_billing_key(TEST_AUTH_VALUE, TEST_CUSTOMER_VALUE)
                self.assert_safe(caught.exception)
                self.assertNotIn("NOT_AN_OBJECT", str(caught.exception))

    def test_issue_billing_key_converts_api_error(self):
        client, _ = self.make_client(
            lambda request: httpx.Response(
                400,
                json={
                    "code": "TEST_ERROR_CODE",
                    "message": TEST_PROVIDER_MESSAGE,
                },
            )
        )
        with self.assertRaises(TossBillingApiError) as caught:
            client.issue_billing_key(TEST_AUTH_VALUE, TEST_CUSTOMER_VALUE)
        self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(caught.exception.code, "TEST_ERROR_CODE")
        self.assert_safe(caught.exception)

    def test_issue_billing_key_handles_non_json_error(self):
        client, _ = self.make_client(
            lambda request: httpx.Response(400, text="TEST_NON_JSON_BODY")
        )
        with self.assertRaises(TossBillingApiError) as caught:
            client.issue_billing_key(TEST_AUTH_VALUE, TEST_CUSTOMER_VALUE)
        self.assertEqual(caught.exception.code, "UNKNOWN_TOSS_ERROR")
        self.assertNotIn("TEST_NON_JSON_BODY", repr(caught.exception))

    def test_issue_billing_key_converts_timeout(self):
        def handler(request):
            raise httpx.ReadTimeout("TEST_TIMEOUT_DETAIL", request=request)

        client, calls = self.make_client(handler)
        with self.assertRaises(TossBillingTransportError) as caught:
            client.issue_billing_key(TEST_AUTH_VALUE, TEST_CUSTOMER_VALUE)
        self.assertEqual(calls, ["POST"])
        self.assert_safe(caught.exception)
        self.assertNotIn("TEST_TIMEOUT_DETAIL", repr(caught.exception))

    def test_issue_billing_key_converts_transport_error(self):
        def handler(request):
            raise httpx.ConnectError("TEST_TRANSPORT_DETAIL", request=request)

        client, calls = self.make_client(handler)
        with self.assertRaises(TossBillingTransportError) as caught:
            client.issue_billing_key(TEST_AUTH_VALUE, TEST_CUSTOMER_VALUE)
        self.assertEqual(calls, ["POST"])
        self.assert_safe(caught.exception)
        self.assertNotIn("TEST_TRANSPORT_DETAIL", repr(caught.exception))

    def test_delete_billing_key_sends_encoded_path(self):
        def handler(request):
            self.assertEqual(request.method, "DELETE")
            self.assertTrue(
                hmac.compare_digest(
                    request.url.raw_path,
                    b"/v1/billing/TEST%20DELETE%2FVALUE%3F",
                )
            )
            return httpx.Response(200, content=b"TEST_BODY_NOT_PARSED")

        client, calls = self.make_client(handler)
        result = client.delete_billing_key("TEST DELETE/VALUE?")
        self.assertIsNone(result)
        self.assertEqual(calls, ["DELETE"])

    def test_delete_billing_key_rejects_invalid_input(self):
        invalid_values = (None, "", "   ", " TEST_VALUE", "TEST_VALUE ", "B" * 201)
        for index, billing_key in enumerate(invalid_values):
            with self.subTest(case=index):
                client, calls = self.make_client(
                    lambda request: self.fail("transport must not be called")
                )
                with self.assertRaises(TossBillingValidationError) as caught:
                    client.delete_billing_key(billing_key)
                self.assertEqual(calls, [])
                self.assert_safe(caught.exception)

    def test_delete_billing_key_converts_api_error(self):
        client, _ = self.make_client(
            lambda request: httpx.Response(
                409,
                json={
                    "code": "TEST_DELETE_ERROR",
                    "message": TEST_PROVIDER_MESSAGE,
                },
            )
        )
        with self.assertRaises(TossBillingApiError) as caught:
            client.delete_billing_key(TEST_BILLING_VALUE)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(caught.exception.code, "TEST_DELETE_ERROR")
        self.assert_safe(caught.exception)

    def test_delete_billing_key_does_not_retry_on_timeout(self):
        def handler(request):
            raise httpx.ReadTimeout("TEST_DELETE_TIMEOUT", request=request)

        client, calls = self.make_client(handler)
        with self.assertRaises(TossBillingTransportError) as caught:
            client.delete_billing_key(TEST_BILLING_VALUE)
        self.assertEqual(calls, ["DELETE"])
        self.assert_safe(caught.exception)
        self.assertNotIn("TEST_DELETE_TIMEOUT", repr(caught.exception))

    def test_from_settings_rejects_missing_secret(self):
        with (
            patch(
                "app.services.toss_billing_client.get_settings",
                return_value=SimpleNamespace(toss_secret_key=None),
            ),
            self.assertRaises(TossBillingConfigurationError) as caught,
        ):
            TossBillingClient.from_settings()
        self.assert_safe(caught.exception)

    def test_close_does_not_close_injected_client(self):
        http_client = MagicMock(spec=httpx.Client)
        client = TossBillingClient(
            SecretStr(TEST_SECRET_VALUE),
            http_client=http_client,
        )
        client.close()
        http_client.close.assert_not_called()

    def test_close_closes_internal_client(self):
        http_client = MagicMock(spec=httpx.Client)
        with patch(
            "app.services.toss_billing_client.httpx.Client",
            return_value=http_client,
        ):
            client = TossBillingClient(SecretStr(TEST_SECRET_VALUE))
        client.close()
        http_client.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
