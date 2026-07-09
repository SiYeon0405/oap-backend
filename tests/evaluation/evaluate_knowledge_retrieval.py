"""DB-backed retrieval evaluation for KnowledgeRetrievalService.

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
DEFAULT_RESULT_PATH = BASE_DIR / "knowledge_retrieval_result.json"
TOP_K = 3

BASELINE_TOTAL_CASES = 20
BASELINE_AVERAGE_KEYWORD_RECALL = 0.80
BASELINE_AVERAGE_LATENCY_MS = 934.08
BASELINE_TOP_K = 3


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
) -> list[dict[str, Any]]:
    return service.retrieve(session=session, query=query, top_k=top_k)


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


def evaluate_case(
    case: dict[str, Any],
    service: KnowledgeRetrievalService,
    session: Session,
) -> dict[str, Any]:
    query = str(case.get("query", ""))
    expected_keywords = [
        str(keyword)
        for keyword in case.get("expectedKeywords", [])
    ]

    started_at = time.perf_counter()
    try:
        chunks = run_retrieval(service, session, query, TOP_K)
        latency_ms = (time.perf_counter() - started_at) * 1000
        retrieved_text = combine_retrieved_text(chunks)
        keyword_result = evaluate_keywords(retrieved_text, expected_keywords)

        return {
            "caseId": case.get("id"),
            "query": query,
            "expectedKeywords": expected_keywords,
            **keyword_result,
            "latencyMs": round(latency_ms, 2),
            "retrievedChunkCount": len(chunks),
        }
    except Exception as exc:
        latency_ms = (time.perf_counter() - started_at) * 1000
        return {
            "caseId": case.get("id"),
            "query": query,
            "expectedKeywords": expected_keywords,
            "matchedKeywords": [],
            "missingKeywords": expected_keywords,
            "keywordRecall": 0.0,
            "latencyMs": round(latency_ms, 2),
            "retrievedChunkCount": 0,
            "error": str(exc),
        }


def evaluate_all(
    cases: list[dict[str, Any]],
    service: KnowledgeRetrievalService,
    session: Session,
) -> list[dict[str, Any]]:
    return [evaluate_case(case, service, session) for case in cases]


def build_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    total_cases = len(results)
    average_keyword_recall = (
        sum(float(result["keywordRecall"]) for result in results) / total_cases
        if total_cases
        else 0.0
    )
    average_latency_ms = (
        sum(float(result["latencyMs"]) for result in results) / total_cases
        if total_cases
        else 0.0
    )

    return {
        "totalCases": total_cases,
        "averageKeywordRecall": round(average_keyword_recall, 4),
        "averageLatencyMs": round(average_latency_ms, 2),
        "topK": TOP_K,
    }


def build_comparison(summary: dict[str, Any]) -> dict[str, Any]:
    current_keyword_recall = float(summary["averageKeywordRecall"])
    current_latency_ms = float(summary["averageLatencyMs"])

    return {
        "baselineAverageKeywordRecall": BASELINE_AVERAGE_KEYWORD_RECALL,
        "currentAverageKeywordRecall": current_keyword_recall,
        "keywordRecallDelta": round(
            current_keyword_recall - BASELINE_AVERAGE_KEYWORD_RECALL,
            4,
        ),
        "baselineAverageLatencyMs": BASELINE_AVERAGE_LATENCY_MS,
        "currentAverageLatencyMs": current_latency_ms,
        "latencyDeltaMs": round(
            current_latency_ms - BASELINE_AVERAGE_LATENCY_MS,
            2,
        ),
    }


def build_payload(results: list[dict[str, Any]]) -> dict[str, Any]:
    summary = build_summary(results)
    return {
        "summary": summary,
        "officialBaseline": {
            "totalCases": BASELINE_TOTAL_CASES,
            "averageKeywordRecall": BASELINE_AVERAGE_KEYWORD_RECALL,
            "averageLatencyMs": BASELINE_AVERAGE_LATENCY_MS,
            "topK": BASELINE_TOP_K,
        },
        "comparison": build_comparison(summary),
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
