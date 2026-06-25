from openai import OpenAI

from app.core.config import get_settings


MODEL_NAME = "gpt-4.1-mini"


def generate_text(prompt: str) -> str:
    settings = get_settings()
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is not configured")

    try:
        client = OpenAI(api_key=settings.openai_api_key)
        response = client.responses.create(
            model=MODEL_NAME,
            input=prompt,
        )
        return response.output_text
    except Exception as exc:
        raise RuntimeError("OpenAI request failed") from exc
