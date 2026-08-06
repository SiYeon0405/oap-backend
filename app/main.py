import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.analysis import reports_router, router as analysis_router
from app.api.analysis_request import router as analysis_request_router
from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.interview import router as interview_router
from app.core.config import get_settings
from app.database.session import get_database_target, verify_database_connection

logger = logging.getLogger(__name__)

app = FastAPI(title="OAP Backend API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:5173",
        "https://www.ooap.co.kr",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(analysis_request_router)
app.include_router(interview_router)
app.include_router(analysis_router)
app.include_router(reports_router)


@app.on_event("startup")
def validate_production_database():
    settings = get_settings()
    if settings.app_env != "production":
        return

    verify_database_connection()
    target = get_database_target()
    logger.info(
        "Database target: driver=%s host=%s port=%s database=%s",
        target["driver"],
        target["host"],
        target["port"],
        target["database"],
    )
