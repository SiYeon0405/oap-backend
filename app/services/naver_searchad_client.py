import base64
import hashlib
import hmac
import json
import logging
import time

import httpx

from app.core.config import get_settings


logger = logging.getLogger(__name__)
API_PATH = "/keywordstool"
BASE_URL = "https://api.searchad.naver.com"


class NaverSearchAdError(RuntimeError):
    pass


class NaverSearchAdClient:
    def __init__(self, http_client=None):
        self.http_client = http_client

    @staticmethod
    def _signature(secret: str, timestamp: str) -> str:
        message = f"{timestamp}.GET.{API_PATH}".encode()
        return base64.b64encode(hmac.new(secret.encode(), message, hashlib.sha256).digest()).decode()

    def fetch_keywords(self, keywords: list[str]) -> list[dict]:
        if not 1 <= len(keywords) <= 5:
            raise ValueError("Naver hintKeywords requires 1 to 5 keywords")

        settings = get_settings()
        credentials = (
            settings.naver_ad_api_key,
            settings.naver_ad_secret_key,
            settings.naver_ad_customer_id,
        )
        if not all(credentials):
            raise NaverSearchAdError("Naver SearchAd credentials are not configured")
        api_key, secret, customer_id = credentials
        timestamp = str(int(time.time() * 1000))
        headers = {
            "X-Timestamp": timestamp,
            "X-API-KEY": api_key,
            "X-Customer": customer_id,
            "X-Signature": self._signature(secret, timestamp),
        }
        client = self.http_client or httpx.Client(timeout=30.0)
        try:
            response = client.get(
                BASE_URL + API_PATH,
                params={
                    "hintKeywords": ",".join("".join(value.split()) for value in keywords),
                    "showDetail": "1",
                },
                headers=headers,
            )
            response.raise_for_status()
            try:
                rows = response.json()["keywordList"]
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                raise NaverSearchAdError("Malformed Naver SearchAd response") from exc
            if not rows:
                logger.warning("Naver SearchAd returned an empty keywordList")
            return rows
        except httpx.HTTPError as exc:
            raise NaverSearchAdError("Naver SearchAd request failed") from exc
        finally:
            if self.http_client is None:
                client.close()
