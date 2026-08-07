import logging

from app.ai.report_ai import REPORT_KEYS
from app.repositories.report_citation_repository import ReportCitationRepository


logger = logging.getLogger(__name__)


class ReportCitationService:
    def __init__(
        self,
        repository: ReportCitationRepository | None = None,
    ):
        self.repository = repository or ReportCitationRepository()

    def save_report_citations(
        self,
        session,
        *,
        analysis_report_id: int,
        retrieval_run_id: int,
        section_evidence_ids: dict[str, list[int]],
    ) -> None:
        valid_section_evidence_ids = self.validate_section_evidence_ids(
            session,
            retrieval_run_id=retrieval_run_id,
            section_evidence_ids=section_evidence_ids,
        )
        self.repository.replace_report_citations(
            session,
            analysis_report_id,
            valid_section_evidence_ids,
        )

    def validate_section_evidence_ids(
        self,
        session,
        *,
        retrieval_run_id: int,
        section_evidence_ids: dict[str, list[int]],
    ) -> dict[str, list[int]]:
        candidate_ids = [
            evidence_id
            for section_key in REPORT_KEYS
            for evidence_id in section_evidence_ids.get(section_key, [])
            if isinstance(evidence_id, int)
        ]
        evidences = self.repository.find_evidences_by_ids(session, candidate_ids)
        allowed_ids = {
            evidence.id
            for evidence in evidences
            if evidence.retrieval_run_id == retrieval_run_id
        }

        result = {}
        for section_key in REPORT_KEYS:
            seen = set()
            valid_ids = []
            for evidence_id in section_evidence_ids.get(section_key, []):
                if not isinstance(evidence_id, int):
                    continue
                if evidence_id not in allowed_ids or evidence_id in seen:
                    continue
                seen.add(evidence_id)
                valid_ids.append(evidence_id)
            result[section_key] = valid_ids

        removed_count = len(set(candidate_ids)) - len(allowed_ids)
        if removed_count:
            logger.warning(
                "Removed invalid report evidence IDs count=%s",
                removed_count,
            )

        return result

    def sanitize_report_evidence_ids(
        self,
        report_payload: dict,
        valid_section_evidence_ids: dict[str, list[int]],
    ) -> dict:
        for section_key in REPORT_KEYS:
            self._sanitize_nested_evidence(
                report_payload.get(section_key),
                set(valid_section_evidence_ids.get(section_key, [])),
            )
        return report_payload

    def _sanitize_nested_evidence(self, value, allowed_ids: set[int]) -> None:
        if isinstance(value, dict):
            for key in ("evidenceIds", "evidence_ids"):
                if key not in value:
                    continue
                original = value.get(key) if isinstance(value.get(key), list) else []
                valid = [
                    evidence_id
                    for evidence_id in dict.fromkeys(original)
                    if isinstance(evidence_id, int) and evidence_id in allowed_ids
                ]
                if len(valid) != len(original):
                    logger.warning(
                        "Removed invalid nested evidence IDs count=%s",
                        len(original) - len(valid),
                    )
                value[key] = valid
                if original and not valid:
                    self._null_unsubstantiated_observed_values(value)
            for nested_key, nested_value in value.items():
                if nested_key not in {"evidenceIds", "evidence_ids"}:
                    self._sanitize_nested_evidence(nested_value, allowed_ids)
        elif isinstance(value, list):
            for item in value:
                self._sanitize_nested_evidence(item, allowed_ids)

    @staticmethod
    def _null_unsubstantiated_observed_values(value: dict) -> None:
        if value.get("valueType") != "observed":
            return
        for key in (
            "value",
            "score",
            "mentionCount",
            "positiveMentionRate",
            "searchGrowthRate",
            "brandCount",
            "brandRate",
            "copyCount",
            "saturationScore",
            "opportunityScore",
        ):
            if key in value:
                value[key] = None

    def get_citations_by_analysis_request_id(
        self,
        session,
        analysis_request_id: int,
    ) -> dict[str, list[dict]]:
        citations = self.repository.find_by_analysis_request_id(
            session,
            analysis_request_id,
        )
        result = {section_key: [] for section_key in REPORT_KEYS}
        seen_sources = {section_key: set() for section_key in REPORT_KEYS}
        for citation in citations:
            evidence = citation.retrieval_evidence
            metadata = self._normalize_reference_metadata(
                evidence.metadata_snapshot or {}
            )
            source_key = self._reference_key(
                metadata,
                citation.retrieval_evidence_id,
            )
            section_seen = seen_sources.setdefault(citation.section_key, set())
            if source_key in section_seen:
                continue
            section_seen.add(source_key)
            result.setdefault(citation.section_key, []).append(
                {
                    "evidence_id": citation.retrieval_evidence_id,
                    "content": evidence.content_snapshot,
                    "source": self._build_source(evidence),
                    "metadata": metadata,
                }
            )
        return result

    @staticmethod
    def _normalize_reference_metadata(metadata: dict) -> dict:
        normalized = dict(metadata)
        aliases = {
            "sourceIdentifier": "source_identifier",
            "publishedAt": "published_at",
            "collectedAt": "collected_at",
            "dataPeriod": "data_period",
            "sampleSize": "sample_size",
            "sourceType": "source_type",
            "displayCode": "display_code",
        }
        for api_key, stored_key in aliases.items():
            if api_key not in normalized and normalized.get(stored_key) is not None:
                normalized[api_key] = normalized[stored_key]
        return normalized

    @staticmethod
    def _reference_key(metadata: dict, evidence_id: int) -> tuple:
        url = metadata.get("url")
        if isinstance(url, str) and url.strip():
            return ("url", url.strip().rstrip("/").lower())
        source_identifier = metadata.get("sourceIdentifier")
        if isinstance(source_identifier, str) and source_identifier.strip():
            return ("sourceIdentifier", source_identifier.strip().lower())
        source_path = metadata.get("source_path")
        if isinstance(source_path, str) and source_path.strip():
            return ("source_path", source_path.strip().lower())
        descriptive = tuple(
            str(metadata.get(key) or "").strip().lower()
            for key in ("title", "publisher", "publishedAt")
        )
        if any(descriptive):
            return ("descriptive", *descriptive)
        return ("evidence", evidence_id)

    def _build_source(self, evidence) -> str:
        metadata = evidence.metadata_snapshot or {}
        parts = []
        if evidence.document_id_snapshot is not None:
            parts.append(f"document_id={evidence.document_id_snapshot}")
        if evidence.chunk_index_snapshot is not None:
            parts.append(f"chunk_index={evidence.chunk_index_snapshot}")
        for key in ("title", "source", "source_path", "domain", "category"):
            value = metadata.get(key)
            if value:
                parts.append(f"{key}={value}")
        return ", ".join(parts)
