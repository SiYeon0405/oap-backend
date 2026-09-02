import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.fernet import Fernet
from pydantic import SecretStr

import app.services.billing_security as billing_security
from app.services.billing_security import (
    BillingKeyCipher,
    BillingKeyDecryptionError,
    BillingKeyEncryptionError,
    BillingSecurityConfigurationError,
)


TEST_PLAIN_VALUE = "TEST_PLAIN_VALUE"
TEST_INVALID_KEY = "TEST_INVALID_FERNET_KEY"
TEST_NON_ASCII_TOKEN = "TEST_NON_ASCII_값"


class BillingKeyCipherTest(unittest.TestCase):
    @staticmethod
    def temporary_key() -> SecretStr:
        return SecretStr(Fernet.generate_key().decode("ascii"))

    def make_cipher(self) -> BillingKeyCipher:
        return BillingKeyCipher(self.temporary_key())

    def assert_hidden(self, error, *sensitive_values) -> None:
        rendered = f"{error!s} {error!r}"
        for sensitive in sensitive_values:
            if sensitive.strip():
                self.assertNotIn(sensitive, rendered)
            else:
                expected = {
                    BillingKeyEncryptionError: "Billing key cannot be encrypted",
                    BillingKeyDecryptionError: "Billing key cannot be decrypted",
                    BillingSecurityConfigurationError: "Billing encryption is not configured",
                }[type(error)]
                self.assertEqual(str(error), expected)

    def test_encrypt_and_decrypt_round_trip(self):
        key = self.temporary_key()
        cipher = BillingKeyCipher(key)
        encrypted = cipher.encrypt(TEST_PLAIN_VALUE)

        self.assertIsInstance(encrypted, str)
        self.assertNotEqual(encrypted, TEST_PLAIN_VALUE)
        self.assertEqual(cipher.decrypt(encrypted), TEST_PLAIN_VALUE)
        self.assertNotIn(key.get_secret_value(), repr(cipher))

    def test_encrypt_uses_randomized_tokens(self):
        cipher = self.make_cipher()
        first = cipher.encrypt(TEST_PLAIN_VALUE)
        second = cipher.encrypt(TEST_PLAIN_VALUE)

        self.assertNotEqual(first, second)
        self.assertEqual(cipher.decrypt(first), TEST_PLAIN_VALUE)
        self.assertEqual(cipher.decrypt(second), TEST_PLAIN_VALUE)

    def test_encrypt_rejects_empty_or_whitespace_input(self):
        cipher = self.make_cipher()
        for value in ("", " ", "\t", "\n"):
            with self.subTest(kind=repr(value)), self.assertRaises(
                BillingKeyEncryptionError
            ) as caught:
                cipher.encrypt(value)
            self.assert_hidden(caught.exception, value)

    def test_decrypt_rejects_empty_or_whitespace_input(self):
        cipher = self.make_cipher()
        for value in ("", " ", "\t", "\n"):
            with self.subTest(kind=repr(value)), self.assertRaises(
                BillingKeyDecryptionError
            ) as caught:
                cipher.decrypt(value)
            self.assert_hidden(caught.exception, value)

    def test_decrypt_rejects_tampered_token(self):
        cipher = self.make_cipher()
        encrypted = cipher.encrypt(TEST_PLAIN_VALUE)
        position = len(encrypted) // 2
        replacement = "A" if encrypted[position] != "A" else "B"
        tampered = encrypted[:position] + replacement + encrypted[position + 1 :]

        with self.assertRaises(BillingKeyDecryptionError) as caught:
            cipher.decrypt(tampered)
        self.assert_hidden(caught.exception, encrypted, tampered, "InvalidToken")

    def test_decrypt_rejects_non_ascii_token(self):
        cipher = self.make_cipher()
        with self.assertRaises(BillingKeyDecryptionError) as caught:
            cipher.decrypt(TEST_NON_ASCII_TOKEN)
        self.assert_hidden(caught.exception, TEST_NON_ASCII_TOKEN)

    def test_decrypt_rejects_non_utf8_plaintext(self):
        key = self.temporary_key()
        token = Fernet(key.get_secret_value().encode("ascii")).encrypt(b"\xff")
        encoded_token = token.decode("ascii")
        cipher = BillingKeyCipher(key)

        with self.assertRaises(BillingKeyDecryptionError) as caught:
            cipher.decrypt(encoded_token)
        self.assert_hidden(caught.exception, encoded_token)

    def test_rejects_invalid_fernet_key(self):
        with self.assertRaises(BillingSecurityConfigurationError) as caught:
            BillingKeyCipher(SecretStr(TEST_INVALID_KEY))
        self.assert_hidden(caught.exception, TEST_INVALID_KEY, "Fernet key")

    def test_rejects_empty_key(self):
        for value in ("", " "):
            with self.subTest(kind=repr(value)), self.assertRaises(
                BillingSecurityConfigurationError
            ) as caught:
                BillingKeyCipher(SecretStr(value))
            self.assert_hidden(caught.exception, value)

    def test_from_settings_rejects_missing_key(self):
        with (
            patch(
                "app.services.billing_security.get_settings",
                return_value=SimpleNamespace(toss_billing_encryption_key=None),
            ),
            self.assertRaises(BillingSecurityConfigurationError) as caught,
        ):
            BillingKeyCipher.from_settings()
        self.assert_hidden(caught.exception)

    def test_from_settings_uses_secret_str(self):
        key = self.temporary_key()
        with patch(
            "app.services.billing_security.get_settings",
            return_value=SimpleNamespace(toss_billing_encryption_key=key),
        ):
            cipher = BillingKeyCipher.from_settings()
        encrypted = cipher.encrypt(TEST_PLAIN_VALUE)
        self.assertEqual(cipher.decrypt(encrypted), TEST_PLAIN_VALUE)
        self.assertNotIn(key.get_secret_value(), repr(cipher))

    def test_decrypt_rejects_token_from_different_key(self):
        first_key = self.temporary_key()
        second_key = self.temporary_key()
        token = BillingKeyCipher(first_key).encrypt(TEST_PLAIN_VALUE)

        with self.assertRaises(BillingKeyDecryptionError) as caught:
            BillingKeyCipher(second_key).decrypt(token)
        self.assert_hidden(
            caught.exception,
            first_key.get_secret_value(),
            second_key.get_secret_value(),
            token,
        )

    def test_errors_do_not_expose_sensitive_values(self):
        with self.assertRaises(BillingSecurityConfigurationError) as invalid_key:
            BillingKeyCipher(SecretStr(TEST_INVALID_KEY))

        cipher = self.make_cipher()
        invalid_plaintext = "TEST_SENSITIVE_\ud800"
        with self.assertRaises(BillingKeyEncryptionError) as encryption_error:
            cipher.encrypt(invalid_plaintext)

        damaged_token = "TEST_DAMAGED_TOKEN"
        with self.assertRaises(BillingKeyDecryptionError) as decryption_error:
            cipher.decrypt(damaged_token)

        self.assert_hidden(invalid_key.exception, TEST_INVALID_KEY)
        self.assert_hidden(encryption_error.exception, invalid_plaintext)
        self.assert_hidden(decryption_error.exception, damaged_token)

    def test_module_has_no_eager_cipher_or_fernet_instance(self):
        values = vars(billing_security).values()
        self.assertFalse(any(isinstance(value, BillingKeyCipher) for value in values))
        self.assertFalse(any(isinstance(value, Fernet) for value in values))


if __name__ == "__main__":
    unittest.main()
