from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings

_engine = None


def get_engine():
    global _engine

    if _engine is not None:
        return _engine

    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    _engine = create_engine(settings.database_url, pool_pre_ping=True)
    return _engine


def get_session():
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())
    return session_local()
