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
