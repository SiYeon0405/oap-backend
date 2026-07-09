"""Compare DB-backed retrieval with and without metadata category filtering.

WARNING: Running this script may call the OpenAI Embeddings API through
app.services.embedding_service.EmbeddingService.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.knowledge_retrieval_service import KnowledgeRetrievalService


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_QUERY_PATH = BASE_DIR / "rag_queries.json"
DEFAULT_RESULT_PATH = BASE_DIR / "knowledge_metadata_filter_comparison_result.json"
DEFAULT_TOP_K = 3

BASELINE_TOTAL_CASES = 20
BASELINE_AVERAGE_KEYWORD_RECALL = 0.80
BASELINE_AVERAGE_LATENCY_MS = 934.08
BASELINE_TOP_K = 3

CASE_CATEGORY_MAP = {
    "RAG-001": "market",
    "RAG-002": "customer",
    "RAG-003": "platform",
    "RAG-004": "competitor",
    "RAG-005": "customer",
    "RAG-006": "market",
    "RAG-007": "platform",
    "RAG-008": "customer",
    "RAG-009": "marketing",
    "RAG-010": "competitor",
    "RAG-011": "platform",
    "RAG-012": "customer",
    "RAG-013": "platform",
    "RAG-014": "competitor",
    "RAG-015": "platform",
    "RAG-016": "customer",
    "RAG-017": "market",
    "RAG-018": "competitor",
    "RAG-019": "marketing",
    "RAG-020": "marketing",
}


def load_rag_queries(path: str | Path) -> list[dict[str, Any]]:
    query_path = Path(path)
    return json.loads(query_path.read_text(encoding="utf-8"))


def get_database_url() -> str:
    database_url = os.getenv("DATABASE_URL") or os.getenv("SQLALCHEMY_DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL or SQLALCHEMY_DATABASE_URL environment variable is required."
        )
    return database_url


def run_retrieval(
    service: KnowledgeRetrievalService,
    session: Session,
    query: str,
    top_k: int,
    metadata_filter: dict[str, str] | None,
) -> list[dict[str, Any]]:
    return service.retrieve(
        session=session,
        query=query,
        top_k=top_k,
        metadata_filter=metadata_filter,
    )


def combine_retrieved_text(chunks: list[dict[str, Any]]) -> str:
    return "\n\n".join(str(chunk.get("content", "")) for chunk in chunks)


def evaluate_keywords(
    retrieved_text: str,
    expected_keywords: list[str],
) -> dict[str, Any]:
    matched_keywords = [
        keyword
        for keyword in expected_keywords
        if keyword and keyword in retrieved_text
    ]
    missing_keywords = [
        keyword
        for keyword in expected_keywords
        if keyword and keyword not in retrieved_text
    ]
    keyword_recall = (
        len(matched_keywords) / len(expected_keywords)
        if expected_keywords
        else 0.0
    )

    return {
        "matchedKeywords": matched_keywords,
        "missingKeywords": missing_keywords,
        "keywordRecall": keyword_recall,
    }


def evaluate_retrieval_variant(
    service: KnowledgeRetrievalService,
    session: Session,
    query: str,
    top_k: int,
    expected_keywords: list[str],
    metadata_filter: dict[str, str] | None,
) -> dict[str, Any]:
    started_at = time.perf_counter()
    chunks = run_retrieval(service, session, query, top_k, metadata_filter)
    latency_ms = (time.perf_counter() - started_at) * 1000
    retrieved_text = combine_retrieved_text(chunks)
    keyword_result = evaluate_keywords(retrieved_text, expected_keywords)

    return {
        **keyword_result,
        "latencyMs": round(latency_ms, 2),
        "retrievedChunkCount": len(chunks),
    }


def failed_retrieval_result(exc: Exception) -> dict[str, Any]:
    return {
        "matchedKeywords": [],
        "missingKeywords": [],
        "keywordRecall": 0.0,
        "latencyMs": 0.0,
        "retrievedChunkCount": 0,
        "error": str(exc),
    }


def evaluate_case(
    case: dict[str, Any],
    service: KnowledgeRetrievalService,
    session: Session,
) -> dict[str, Any]:
    case_id = str(case.get("id", ""))
    query = str(case.get("query", ""))
    top_k = int(case.get("topK", DEFAULT_TOP_K))
    category = CASE_CATEGORY_MAP.get(case_id, "general")
    expected_keywords = [
        str(keyword)
        for keyword in case.get("expectedKeywords", [])
    ]

    try:
        without_filter = evaluate_retrieval_variant(
            service=service,
            session=session,
            query=query,
            top_k=top_k,
            expected_keywords=expected_keywords,
            metadata_filter=None,
        )
    except Exception as exc:
        without_filter = failed_retrieval_result(exc)

    try:
        with_category_filter = evaluate_retrieval_variant(
            service=service,
            session=session,
            query=query,
            top_k=top_k,
            expected_keywords=expected_keywords,
            metadata_filter={"category": category},
        )
    except Exception as exc:
        with_category_filter = failed_retrieval_result(exc)

    return {
        "caseId": case_id,
        "query": query,
        "topK": top_k,
        "category": category,
        "expectedKeywords": expected_keywords,
        "withoutFilter": without_filter,
        "withCategoryFilter": with_category_filter,
    }


def evaluate_all(
    cases: list[dict[str, Any]],
    service: KnowledgeRetrievalService,
    session: Session,
) -> list[dict[str, Any]]:
    return [evaluate_case(case, service, session) for case in cases]


def average_metric(
    results: list[dict[str, Any]],
    variant: str,
    metric: str,
) -> float:
    total_cases = len(results)
    return (
        sum(float(result[variant][metric]) for result in results) / total_cases
        if total_cases
        else 0.0
    )


def build_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    total_cases = len(results)
    without_filter_recall = average_metric(results, "withoutFilter", "keywordRecall")
    without_filter_latency = average_metric(results, "withoutFilter", "latencyMs")
    with_filter_recall = average_metric(results, "withCategoryFilter", "keywordRecall")
    with_filter_latency = average_metric(results, "withCategoryFilter", "latencyMs")

    return {
        "totalCases": total_cases,
        "topK": DEFAULT_TOP_K,
        "withoutFilter": {
            "averageKeywordRecall": round(without_filter_recall, 4),
            "averageLatencyMs": round(without_filter_latency, 2),
        },
        "withCategoryFilter": {
            "averageKeywordRecall": round(with_filter_recall, 4),
            "averageLatencyMs": round(with_filter_latency, 2),
        },
        "delta": {
            "keywordRecallDelta": round(
                with_filter_recall - without_filter_recall,
                4,
            ),
            "latencyDeltaMs": round(
                with_filter_latency - without_filter_latency,
                2,
            ),
        },
    }


def build_payload(results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "summary": build_summary(results),
        "officialBaseline": {
            "totalCases": BASELINE_TOTAL_CASES,
            "averageKeywordRecall": BASELINE_AVERAGE_KEYWORD_RECALL,
            "averageLatencyMs": BASELINE_AVERAGE_LATENCY_MS,
            "topK": BASELINE_TOP_K,
        },
        "cases": results,
    }


def main() -> None:
    cases = load_rag_queries(DEFAULT_QUERY_PATH)
    engine = create_engine(get_database_url())
    service = KnowledgeRetrievalService()

    with Session(engine) as session:
        results = evaluate_all(cases, service, session)

    payload = build_payload(results)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    with DEFAULT_RESULT_PATH.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
