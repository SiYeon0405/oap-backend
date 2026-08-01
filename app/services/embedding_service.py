from app.ai.openai_client import get_openai_client


class EmbeddingService:
    EMBEDDING_DIMENSION = 1536

    def __init__(self, model: str = "text-embedding-3-small"):
        self.model = model
        self.client = get_openai_client()

    def embed_text(self, text: str) -> list[float]:
        self._validate_text(text)

        response = self.client.embeddings.create(
            model=self.model,
            input=text,
        )
        return response.data[0].embedding

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        for text in texts:
            self._validate_text(text)

        response = self.client.embeddings.create(
            model=self.model,
            input=texts,
        )
        return [item.embedding for item in response.data]

    @staticmethod
    def _validate_text(text: str) -> None:
        if not text or not text.strip():
            raise ValueError("Input text must not be empty.")
