"""Database engine and session helpers."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings

settings = get_settings()

_connect_args = {}
if settings.sqlalchemy_url.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}


def _explain_bad_url(raw: str) -> str:
    """Why DATABASE_URL could not be used, in words worth reading in a log."""
    if not raw.strip():
        return "DATABASE_URL is empty. Set it to a Postgres URL, or unset it to fall back to sqlite."
    if "${{" in raw or "${" in raw:
        # An unresolved reference carries no credentials, so it is safe to echo.
        return (
            f"DATABASE_URL is still an unresolved variable reference ({raw!r}). "
            "On Railway that means no service by that name exists yet: create the "
            "Postgres service first, then trigger a NEW deploy. Restart and Redeploy "
            "both reuse the previous deployment's variables and will not pick it up."
        )
    return (
        "DATABASE_URL is not a URL SQLAlchemy can parse. It should look like "
        "postgresql://user:password@host:5432/dbname"
    )


try:
    engine = create_engine(
        settings.sqlalchemy_url,
        pool_pre_ping=True,
        pool_recycle=280,
        connect_args=_connect_args,
    )
except ArgumentError as exc:
    raise RuntimeError(_explain_bad_url(settings.database_url)) from exc

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Standalone session for the worker thread."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
