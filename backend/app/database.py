from __future__ import annotations

import os
from collections.abc import Generator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DEFAULT_SQLITE_PATH = "sqlite:///./pocketwise.db"


def normalise_url(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    if url.startswith("postgres+psycopg2://"):
        return url.replace("postgres+psycopg2://", "postgresql://", 1)
    return url


def build_engine(url: str | None = None, *, echo: bool = False) -> Engine:
    target = normalise_url(url or os.getenv("DATABASE_URL") or DEFAULT_SQLITE_PATH)
    kwargs: dict[str, object] = {"echo": echo, "future": True}
    if target.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs["pool_pre_ping"] = True
        kwargs["pool_recycle"] = 300
    return create_engine(target, **kwargs)


def migration_url(engine: Engine) -> str:
    """Render an engine's connection string for Alembic.

    `str(engine.url)` and `url.render_as_string()` both hide the password,
    printing `***` instead. Alembic then connects with that literal password
    and every migration against a real server fails with "password
    authentication failed".

    The bug is invisible on SQLite, which has no password, and to a test
    suite that only ever points at SQLite -- which is precisely how it
    survived. This function exists so the behaviour has a name and a test.

    The trailing `%` doubling is ConfigParser interpolation: Alembic's
    config object reads `%%` back as a literal `%` in the final URL.
    """
    return engine.url.render_as_string(hide_password=False).replace("%", "%%")


engine = build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
