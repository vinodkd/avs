from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from axedup import config
from axedup.models.schema import Base


def _get_engine() -> Engine:
    url = f"sqlite:///{config.DB_PATH}"
    engine = create_engine(url, echo=False)

    # Enable WAL mode for better concurrent read performance
    @event.listens_for(engine, "connect")
    def set_wal(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA journal_mode=WAL")
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    return engine


_engine: Engine | None = None
_SessionFactory: sessionmaker | None = None


def init_db() -> None:
    """Create tables and prepare the session factory. Call once at startup."""
    global _engine, _SessionFactory
    config.ensure_dirs()
    _engine = _get_engine()
    Base.metadata.create_all(_engine)
    _SessionFactory = sessionmaker(bind=_engine, expire_on_commit=False)


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("Database not initialised — call init_db() first")
    return _engine


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Yield a SQLAlchemy session, committing on success or rolling back on error."""
    if _SessionFactory is None:
        raise RuntimeError("Database not initialised — call init_db() first")
    session = _SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
