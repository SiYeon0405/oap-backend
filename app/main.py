from fastapi import FastAPI

from app.api.analysis import router as analysis_router
from app.api.analysis_request import router as analysis_request_router
from app.api.health import router as health_router
from app.api.interview import router as interview_router

app = FastAPI(title="OAP Backend API")

app.include_router(health_router)
app.include_router(analysis_request_router)
app.include_router(interview_router)
app.include_router(analysis_router)
