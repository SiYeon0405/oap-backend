from sqlalchemy.orm import Session

from app.models.analysis_request import AnalysisRequest


class AnalysisRequestRepository:
    def save(self, session: Session, analysis_request: AnalysisRequest) -> AnalysisRequest:
        session.add(analysis_request)
        session.commit()
        session.refresh(analysis_request)
        return analysis_request

    def update_keyword_collection_status(
        self,
        session: Session,
        analysis_request_id: int,
        status: str,
    ) -> bool:
        analysis_request = session.get(AnalysisRequest, analysis_request_id)
        if analysis_request is None:
            return False
        analysis_request.keyword_collection_status = status
        session.commit()
        return True
