from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.database.session import get_database_target, get_session

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
def health_check():
    return {"status": "ok"}


@router.get("/db")
def database_health_check():
    try:
        with get_session() as session:
            session.execute(text("SELECT 1"))
    except (RuntimeError, SQLAlchemyError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database connection failed",
        ) from exc

    target = get_database_target()
    return {
        "status": "ok",
        "database": "connected",
        "driver": target["driver"],
        "host": target["host"],
        "port": target["port"],
        "databaseName": target["database"],
    }
