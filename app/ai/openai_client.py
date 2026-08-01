from functools import lru_cache

from openai import OpenAI

from app.core.config import get_openai_api_key


MODEL_NAME = "gpt-4.1-mini"


@lru_cache
def get_openai_client() -> OpenAI:
    return OpenAI(api_key=get_openai_api_key())


def generate_text(prompt: str) -> str:
    try:
        client = get_openai_client()
        response = client.responses.create(
            model=MODEL_NAME,
            input=prompt,
        )
        return response.output_text
    except Exception as exc:
        raise RuntimeError("OpenAI request failed") from exc
