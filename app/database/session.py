from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.config import get_database_url

_engine = None
_session_factory = None


def get_engine():
    global _engine

    if _engine is not None:
        return _engine

    _engine = create_engine(get_database_url(), pool_pre_ping=True)
    return _engine


def get_session_factory():
    global _session_factory

    if _session_factory is None:
        _session_factory = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=get_engine(),
        )
    return _session_factory


def get_session():
    return get_session_factory()()


def get_database_target() -> dict[str, str | int | None]:
    parsed = make_url(get_database_url())
    return {
        "driver": parsed.drivername,
        "host": parsed.host,
        "port": parsed.port,
        "database": parsed.database,
    }


def verify_database_connection() -> None:
    with get_engine().connect() as connection:
        connection.execute(text("SELECT 1"))
