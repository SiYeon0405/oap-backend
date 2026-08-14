from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.search_keyword import Keyword, KeywordMetric, ReportEvidence


class KeywordRepository:
    def add_metrics(
        self,
        session: Session,
        rows: list[dict],
        analysis_request_id: int,
    ) -> list[KeywordMetric]:
        row_by_keyword = {}
        for row in rows:
            row_by_keyword.setdefault(row["keyword"], row)
        keyword_values = list(row_by_keyword)
        keywords_by_value = {}
        for offset in range(0, len(keyword_values), 1000):
            chunk = keyword_values[offset:offset + 1000]
            keywords_by_value.update(
                (keyword.keyword, keyword)
                for keyword in session.scalars(select(Keyword).where(Keyword.keyword.in_(chunk)))
            )

        missing_values = [value for value in keyword_values if value not in keywords_by_value]
        if missing_values and session.get_bind().dialect.name == "postgresql":
            created_at = datetime.now(timezone.utc)
            for offset in range(0, len(missing_values), 1000):
                chunk = missing_values[offset:offset + 1000]
                session.execute(
                    pg_insert(Keyword)
                    .values([
                        {
                            "keyword": value,
                            "keyword_raw": row_by_keyword[value]["keyword_raw"],
                            "created_at": created_at,
                        }
                        for value in chunk
                    ])
                    .on_conflict_do_nothing(index_elements=[Keyword.keyword])
                )
                keywords_by_value.update(
                    (keyword.keyword, keyword)
                    for keyword in session.scalars(
                        select(Keyword).where(Keyword.keyword.in_(chunk))
                    )
                )
        elif missing_values:
            new_keywords = [
                Keyword(
                    keyword=value,
                    keyword_raw=row_by_keyword[value]["keyword_raw"],
                    created_at=datetime.now(timezone.utc),
                )
                for value in missing_values
            ]
            session.add_all(new_keywords)
            session.flush()
            keywords_by_value.update((keyword.keyword, keyword) for keyword in new_keywords)

        metrics = [
            KeywordMetric(
                keyword_id=keywords_by_value[row["keyword"]].id,
                analysis_request_id=analysis_request_id,
                seed_type=row["seed_type"],
                **row["metric"],
            )
            for row in rows
        ]
        session.add_all(metrics)
        session.commit()
        return metrics

    def latest_metric(self, session: Session, keyword_id: int) -> KeywordMetric | None:
        return session.scalar(
            select(KeywordMetric)
            .where(KeywordMetric.keyword_id == keyword_id)
            .order_by(KeywordMetric.collected_at.desc())
            .limit(1)
        )

    def find_metrics_by_analysis_request(
        self,
        session: Session,
        analysis_request_id: int,
    ) -> list[tuple[KeywordMetric, Keyword]]:
        return list(
            session.execute(
                select(KeywordMetric, Keyword)
                .join(Keyword, Keyword.id == KeywordMetric.keyword_id)
                .where(KeywordMetric.analysis_request_id == analysis_request_id)
                .order_by(KeywordMetric.collected_at.desc(), KeywordMetric.id)
            ).tuples()
        )

    def add_report_evidence(
        self,
        session: Session,
        *,
        report_id: int,
        metric_id: int,
        evidence_no: int,
        seed_type: str,
    ) -> ReportEvidence:
        evidence = ReportEvidence(
            report_id=report_id,
            metric_id=metric_id,
            evidence_no=evidence_no,
            seed_type=seed_type,
            section="target_customer_analysis",
        )
        session.add(evidence)
        session.commit()
        return evidence
