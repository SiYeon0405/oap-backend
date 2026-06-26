import hashlib
import json
import math
import os
from pathlib import Path

from openai import OpenAI


KNOWLEDGE_DIR = Path(__file__).resolve().parent / "knowledge"
CACHE_PATH = KNOWLEDGE_DIR / ".cache" / "report_knowledge_embeddings.json"
EMBEDDING_MODEL = "text-embedding-3-small"
MAX_CHUNK_LENGTH = 1200


def retrieve_report_knowledge(query: str, top_k: int = 4) -> str:
    try:
        if not query.strip() or not os.getenv("OPENAI_API_KEY"):
            return ""

        chunks = _load_knowledge_chunks()
        if not chunks:
            return ""

        client = OpenAI()
        cached_chunks = _load_or_create_cached_embeddings(client, chunks)
        query_embedding = _embed_texts(client, [query])[0]

        ranked_chunks = sorted(
            cached_chunks,
            key=lambda chunk: _cosine_similarity(
                query_embedding,
                chunk.get("embedding", []),
            ),
            reverse=True,
        )
        selected_chunks = [
            chunk["text"].strip()
            for chunk in ranked_chunks[:top_k]
            if chunk.get("text", "").strip()
        ]
        return "\n\n---\n\n".join(selected_chunks)
    except Exception:
        return ""


def _load_knowledge_chunks() -> list[dict]:
    chunks = []
    for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        for index, chunk_text in enumerate(_split_markdown_chunks(text)):
            chunks.append(
                {
                    "id": f"{path.name}:{index}",
                    "file": path.name,
                    "text": chunk_text,
                    "hash": _content_hash(chunk_text),
                    "mtime": path.stat().st_mtime,
                }
            )
    return chunks


def _split_markdown_chunks(text: str) -> list[str]:
    chunks = []
    current_lines = []

    for line in text.splitlines():
        stripped = line.strip()
        starts_heading = stripped.startswith("#")
        starts_new_paragraph = not stripped

        if (starts_heading or starts_new_paragraph) and current_lines:
            _append_chunk(chunks, "\n".join(current_lines))
            current_lines = []

        if stripped:
            current_lines.append(line)

    if current_lines:
        _append_chunk(chunks, "\n".join(current_lines))

    return chunks


def _append_chunk(chunks: list[str], text: str) -> None:
    text = text.strip()
    if not text:
        return

    while len(text) > MAX_CHUNK_LENGTH:
        chunks.append(text[:MAX_CHUNK_LENGTH].strip())
        text = text[MAX_CHUNK_LENGTH:].strip()
    if text:
        chunks.append(text)


def _load_or_create_cached_embeddings(client: OpenAI, chunks: list[dict]) -> list[dict]:
    cached = _read_cache()
    cached_by_id = {
        item["id"]: item
        for item in cached.get("chunks", [])
        if isinstance(item, dict) and "id" in item
    }

    result = []
    missing_chunks = []
    for chunk in chunks:
        cached_chunk = cached_by_id.get(chunk["id"])
        if (
            cached_chunk
            and cached_chunk.get("hash") == chunk["hash"]
            and cached_chunk.get("mtime") == chunk["mtime"]
            and cached_chunk.get("embedding")
        ):
            result.append(cached_chunk)
        else:
            missing_chunks.append(chunk)

    if missing_chunks:
        embeddings = _embed_texts(client, [chunk["text"] for chunk in missing_chunks])
        for chunk, embedding in zip(missing_chunks, embeddings, strict=True):
            chunk_with_embedding = {**chunk, "embedding": embedding}
            result.append(chunk_with_embedding)
        _write_cache(result)

    return result


def _embed_texts(client: OpenAI, texts: list[str]) -> list[list[float]]:
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts,
    )
    return [item.embedding for item in response.data]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0

    dot_product = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot_product / (left_norm * right_norm)


def _read_cache() -> dict:
    try:
        if CACHE_PATH.exists():
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"chunks": []}


def _write_cache(chunks: list[dict]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(
        json.dumps(
            {
                "embedding_model": EMBEDDING_MODEL,
                "chunks": chunks,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
