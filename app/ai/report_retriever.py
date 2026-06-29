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

        search_query = _build_embedding_search_query(query)
        chunks = _load_knowledge_chunks()
        if not chunks:
            return ""

        client = OpenAI()
        cached_chunks = _load_or_create_cached_embeddings(client, chunks)
        query_embedding = _embed_texts(client, [search_query])[0]

        ranked_chunks = sorted(
            cached_chunks,
            key=lambda chunk: _cosine_similarity(
                query_embedding,
                chunk.get("embedding", []),
            ),
            reverse=True,
        )
        candidate_chunks = ranked_chunks[:5]
        selected_chunks = []
        seen_texts = set()
        for chunk in candidate_chunks:
            text = chunk.get("text", "").strip()
            normalized_text = _normalize_chunk_text(text)
            if not text or normalized_text in seen_texts:
                continue

            selected_chunks.append(text)
            seen_texts.add(normalized_text)
            if len(selected_chunks) >= min(top_k, 3):
                break
        return "\n\n---\n\n".join(selected_chunks)
    except Exception:
        return ""


def _build_embedding_search_query(query: str) -> str:
    try:
        payload = json.loads(query)
    except json.JSONDecodeError:
        return query

    if not isinstance(payload, dict):
        return query

    fields = [
        ("service_name", "서비스명"),
        ("name", "서비스명"),
        ("service_description", "한 줄 설명"),
        ("description", "한 줄 설명"),
        ("industry", "업종"),
        ("business_type", "업종"),
        ("main_question", "메인 질문"),
        ("question", "메인 질문"),
        ("interview_answers", "인터뷰 답변"),
        ("answers", "인터뷰 답변"),
    ]
    parts = []
    for key, label in fields:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(f"{label}: {value.strip()}")
        elif isinstance(value, list):
            values = [str(item).strip() for item in value if str(item).strip()]
            if values:
                parts.append(f"{label}: {' '.join(values)}")

    return "\n".join(parts) if parts else query


def _normalize_chunk_text(text: str) -> str:
    return " ".join(text.split())


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
                    "metadata": {
                        "category": _infer_chunk_category(chunk_text),
                    },
                }
            )
    return chunks


def _infer_chunk_category(text: str) -> str:
    if "경쟁사 분석 기준" in text:
        return "competitor"
    if "국내 플랫폼별 활용 기준" in text:
        return "platform"
    if (
        "초기 창업자와 소규모 브랜드의 저예산 마케팅 원칙" in text
        or "1개월, 2개월, 3개월 실행 로드맵 기준" in text
    ):
        return "marketing"
    if "대한민국 시장 분석 기준" in text:
        return "market"
    if any(keyword in text for keyword in ("고객", "타깃", "페르소나")):
        return "customer"
    return "general"


def _split_markdown_chunks(text: str) -> list[str]:
    chunks = []
    current_lines = []

    for line in text.splitlines():
        stripped = line.strip()
        starts_heading = stripped.startswith("#")

        if starts_heading and current_lines:
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
            result.append(
                {
                    **cached_chunk,
                    "metadata": chunk.get("metadata", cached_chunk.get("metadata", {})),
                }
            )
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
