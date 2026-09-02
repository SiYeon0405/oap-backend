from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr

from app.core.config import Settings, get_settings


class BillingSecurityConfigurationError(RuntimeError):
    pass


class BillingKeyEncryptionError(ValueError):
    pass


class BillingKeyDecryptionError(ValueError):
    pass


class BillingKeyCipher:
    __slots__ = ("_fernet",)

    def __init__(self, encryption_key: SecretStr):
        try:
            self._fernet = Fernet(
                encryption_key.get_secret_value().encode("ascii")
            )
        except (AttributeError, TypeError, ValueError, UnicodeError):
            raise BillingSecurityConfigurationError(
                "Billing encryption is not configured"
            ) from None

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "BillingKeyCipher":
        encryption_key = (
            settings or get_settings()
        ).toss_billing_encryption_key
        if encryption_key is None:
            raise BillingSecurityConfigurationError(
                "Billing encryption is not configured"
            )
        return cls(encryption_key)

    def encrypt(self, plain_billing_key: str) -> str:
        if not isinstance(plain_billing_key, str) or not plain_billing_key.strip():
            raise BillingKeyEncryptionError("Billing key cannot be encrypted")
        try:
            return self._fernet.encrypt(
                plain_billing_key.encode("utf-8")
            ).decode("ascii")
        except (TypeError, ValueError, UnicodeError):
            raise BillingKeyEncryptionError(
                "Billing key cannot be encrypted"
            ) from None

    def decrypt(self, encrypted_billing_key: str) -> str:
        if (
            not isinstance(encrypted_billing_key, str)
            or not encrypted_billing_key.strip()
        ):
            raise BillingKeyDecryptionError("Billing key cannot be decrypted")
        try:
            return self._fernet.decrypt(
                encrypted_billing_key.encode("ascii")
            ).decode("utf-8")
        except (InvalidToken, TypeError, ValueError, UnicodeError):
            raise BillingKeyDecryptionError(
                "Billing key cannot be decrypted"
            ) from None
