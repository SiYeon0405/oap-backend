"""Baseline retrieval evaluation for the current Markdown RAG.

WARNING: Running this script may call the OpenAI Embeddings API through
app.ai.report_retriever.retrieve_report_knowledge().
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.ai.report_retriever import retrieve_report_knowledge


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_QUERY_PATH = BASE_DIR / "rag_queries.json"
DEFAULT_OUTPUT_PATH = BASE_DIR / "results" / "baseline_results.json"
PREVIEW_LENGTH = 500


def load_rag_queries(path: str | Path) -> list[dict[str, Any]]:
    query_path = Path(path)
    return json.loads(query_path.read_text(encoding="utf-8"))


def run_retrieval(query: str, top_k: int) -> str:
    return retrieve_report_knowledge(query, top_k=top_k)


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


def evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    query = str(case.get("query", ""))
    top_k = int(case.get("topK", 3))
    expected_keywords = [
        str(keyword)
        for keyword in case.get("expectedKeywords", [])
    ]

    started_at = time.perf_counter()
    retrieved_text = run_retrieval(query, top_k)
    latency_ms = (time.perf_counter() - started_at) * 1000

    keyword_result = evaluate_keywords(retrieved_text, expected_keywords)

    return {
        "id": case.get("id"),
        "industry": case.get("industry"),
        "query": query,
        "topK": top_k,
        "expectedKeywords": expected_keywords,
        **keyword_result,
        "latencyMs": round(latency_ms, 2),
        "retrievedTextPreview": retrieved_text[:PREVIEW_LENGTH],
    }


def evaluate_all(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [evaluate_case(case) for case in cases]


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
    }


def save_results(results: list[dict[str, Any]], output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "summary": build_summary(results),
        "cases": results,
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    cases = load_rag_queries(DEFAULT_QUERY_PATH)
    results = evaluate_all(cases)
    save_results(results, DEFAULT_OUTPUT_PATH)


if __name__ == "__main__":
    main()
