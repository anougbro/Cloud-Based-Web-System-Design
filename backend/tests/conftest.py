"""Test harness.

Sets DATABASE_URL and SECRET_KEY *before* any app import so `app.database`
binds to an in-memory SQLite engine and `app.security` does not abort on a
missing secret. The in-memory database is shared across threads through a
StaticPool, because Starlette's TestClient runs sync endpoints on a
worker thread and a plain `sqlite:///:memory:` engine would hand that thread
a different, empty database.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Iterator

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", secrets.token_urlsafe(64))
os.environ.setdefault("ENVIRONMENT", "test")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import User
from app.rate_limit import login_limiter, register_limiter
from app.security import hash_password


@pytest.fixture(scope="session")
def engine():
    return create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


@pytest.fixture(scope="session")
def session_factory(engine):
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture(autouse=True)
def reset_state(session_factory) -> Iterator[None]:
    with session_factory() as session:
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(table.delete())
        session.commit()
    login_limiter.reset()
    register_limiter.reset()
    yield


@pytest.fixture
def db(session_factory) -> Iterator[Session]:
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(session_factory) -> Iterator[TestClient]:
    def override() -> Iterator[Session]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def register(
    client: TestClient, email: str = "user@example.com", password: str = "password123"
) -> str:
    response = client.post("/auth/register", json={"email": email, "password": password})
    assert response.status_code == 201, response.text
    return response.json()["access_token"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def make_user(db: Session, email: str, password: str = "password123") -> User:
    user = User(email=email, password_hash=hash_password(password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def token(client: TestClient) -> str:
    return register(client)
