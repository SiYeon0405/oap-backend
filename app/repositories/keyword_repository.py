from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.search_keyword import Keyword, KeywordMetric, ReportEvidence


class KeywordRepository:
    def add_metrics(self, session: Session, rows: list[dict]) -> list[KeywordMetric]:
        metrics = []
        for row in rows:
            keyword = session.scalar(select(Keyword).where(Keyword.keyword == row["keyword"]))
            if keyword is None:
                keyword = Keyword(
                    keyword=row["keyword"],
                    keyword_raw=row["keyword_raw"],
                    created_at=datetime.now(timezone.utc),
                )
                session.add(keyword)
                session.flush()
            metric = KeywordMetric(keyword_id=keyword.id, **row["metric"])
            session.add(metric)
            metrics.append(metric)
        session.commit()
        return metrics

    def latest_metric(self, session: Session, keyword_id: int) -> KeywordMetric | None:
        return session.scalar(
            select(KeywordMetric)
            .where(KeywordMetric.keyword_id == keyword_id)
            .order_by(KeywordMetric.collected_at.desc())
            .limit(1)
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
