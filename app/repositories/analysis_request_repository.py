from sqlalchemy.orm import Session

from app.models.analysis_request import AnalysisRequest


class AnalysisRequestRepository:
    def save(self, session: Session, analysis_request: AnalysisRequest) -> AnalysisRequest:
        session.add(analysis_request)
        session.commit()
        session.refresh(analysis_request)
        return analysis_request
