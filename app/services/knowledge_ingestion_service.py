from pathlib import Path
from typing import Any

from app.repositories.knowledge_repository import KnowledgeRepository
from app.services.embedding_service import EmbeddingService


class KnowledgeIngestionService:
    DEFAULT_CHUNK_SIZE = 1200
    DEFAULT_CHUNK_OVERLAP = 0

    def __init__(
        self,
        repository: KnowledgeRepository | None = None,
        embedding_service: EmbeddingService | None = None,
    ):
        self.repository = repository or KnowledgeRepository()
        self.embedding_service = embedding_service or EmbeddingService()

    def read_markdown(self, path: str | Path) -> str:
        return Path(path).read_text(encoding="utf-8")

    def split_markdown_chunks(
        self,
        text: str,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    ) -> list[str]:
        if chunk_overlap != 0:
            raise ValueError("Only chunk_overlap=0 is supported for MVP baseline parity")

        chunks = []
        current_lines = []

        for line in text.splitlines():
            stripped = line.strip()
            starts_heading = stripped.startswith("#")

            if starts_heading and current_lines:
                self._append_chunk(chunks, "\n".join(current_lines), chunk_size)
                current_lines = []

            if stripped:
                current_lines.append(line)

        if current_lines:
            self._append_chunk(chunks, "\n".join(current_lines), chunk_size)

        return chunks

    def build_document_payload(
        self,
        path: str | Path,
        source_type: str = "markdown",
        domain: str | None = None,
        title: str | None = None,
    ) -> dict[str, Any]:
        source_path = Path(path)
        return {
            "title": title or source_path.stem,
            "source_type": source_type,
            "source_path": str(source_path),
            "domain": domain,
        }

    def build_chunk_payloads(
        self,
        chunks: list[str],
    ) -> list[dict[str, Any]]:
        embeddings = self.embedding_service.embed_texts(chunks) if chunks else []
        return [
            {
                "chunk_index": index,
                "content": chunk,
                "embedding": embeddings[index],
                "metadata": {
                    "category": self._infer_chunk_category(chunk),
                },
            }
            for index, chunk in enumerate(chunks)
        ]

    def prepare_markdown_ingestion(
        self,
        path: str | Path,
        source_type: str = "markdown",
        domain: str | None = None,
        title: str | None = None,
    ) -> dict[str, Any]:
        text = self.read_markdown(path)
        chunks = self.split_markdown_chunks(text)
        return {
            "document": self.build_document_payload(
                path=path,
                source_type=source_type,
                domain=domain,
                title=title,
            ),
            "chunks": self.build_chunk_payloads(chunks),
        }

    def _append_chunk(
        self,
        chunks: list[str],
        text: str,
        chunk_size: int,
    ) -> None:
        text = text.strip()
        if not text:
            return

        while len(text) > chunk_size:
            chunks.append(text[:chunk_size].strip())
            text = text[chunk_size:].strip()
        if text:
            chunks.append(text)

    def _infer_chunk_category(self, text: str) -> str:
        if "경쟁사 분석 기준" in text:
            return "competitor"
        if "국내 플랫폼별 활용 기준" in text:
            return "platform"
        if (
            "초기 창업자와 소규모 브랜드의 저예산 마케팅 원칙" in text
            or "1개월, 2개월, 3개월 실행 로드맵 기준" in text
        ):
            return "marketing"
        if any(
            keyword in text
            for keyword in (
                "고객",
                "타겟",
                "타깃",
                "페르소나",
                "구매 동기",
                "불편",
                "문제",
                "니즈",
                "연령대",
                "주 고객층",
            )
        ):
            return "customer"
        if "대한민국 시장 분석 기준" in text:
            return "market"
        return "general"
