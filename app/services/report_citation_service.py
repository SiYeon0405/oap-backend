from app.ai.report_ai import REPORT_KEYS
from app.repositories.report_citation_repository import ReportCitationRepository


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

        return result

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
        for citation in citations:
            evidence = citation.retrieval_evidence
            result.setdefault(citation.section_key, []).append(
                {
                    "evidence_id": citation.retrieval_evidence_id,
                    "content": evidence.content_snapshot,
                    "source": self._build_source(evidence),
                    "metadata": evidence.metadata_snapshot or {},
                }
            )
        return result

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
