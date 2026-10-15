from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from conftest import auth, make_user, register
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RevokedToken, User
from app.security import SECRET, hash_password, needs_rehash, verify_password


def test_registration_returns_a_usable_token(client: TestClient) -> None:
    response = client.post(
        "/auth/register", json={"email": "new@example.com", "password": "password123"}
    )
    assert response.status_code == 201
    assert response.json()["token_type"] == "bearer"
    assert client.get("/summary", headers=auth(response.json()["access_token"])).status_code == 200


def test_duplicate_email_is_rejected_case_insensitively(client: TestClient) -> None:
    register(client, "a@example.com")
    duplicate = client.post(
        "/auth/register", json={"email": "A@Example.com", "password": "password123"}
    )
    assert duplicate.status_code == 409


def test_login_succeeds_and_fails_with_a_generic_message(client: TestClient) -> None:
    register(client, "a@example.com")
    ok = client.post("/auth/login", json={"email": "A@EXAMPLE.COM", "password": "password123"})
    assert ok.status_code == 200
    wrong = client.post("/auth/login", json={"email": "a@example.com", "password": "wrongpassword"})
    assert wrong.status_code == 401
    missing = client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": "wrongpassword"}
    )
    assert missing.status_code == 401
    assert missing.json()["detail"] == wrong.json()["detail"]


def test_login_does_not_reveal_account_existence_through_latency(client: TestClient) -> None:
    register(client, "known@example.com")

    def median_latency(email: str) -> float:
        samples = []
        for _ in range(3):
            start = time.perf_counter()
            client.post("/auth/login", json={"email": email, "password": "wrongpassword"})
            samples.append(time.perf_counter() - start)
        return sorted(samples)[1]

    known = median_latency("known@example.com")
    unknown = median_latency("absent@example.com")

    assert known / unknown < 3.0, f"timing oracle: known={known:.4f}s unknown={unknown:.4f}s"


def test_failed_logins_are_rate_limited(client: TestClient) -> None:
    register(client, "a@example.com")
    statuses = [
        client.post(
            "/auth/login", json={"email": "a@example.com", "password": "wrongpassword"}
        ).status_code
        for _ in range(12)
    ]
    assert 429 in statuses
    assert (
        client.post(
            "/auth/login", json={"email": "a@example.com", "password": "password123"}
        ).status_code
        == 429
    )


def test_password_never_appears_in_validation_errors(client: TestClient) -> None:
    secret_value = "Zq7!v"
    response = client.post("/auth/login", json={"email": "a@example.com", "password": secret_value})

    assert response.status_code == 422
    assert secret_value not in response.text
    assert "input" not in response.text
    detail = response.json()["detail"][0]
    assert detail["loc"] == ["body", "password"]
    assert detail["type"] == "string_too_short"


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer not-a-jwt"},
        {"Authorization": "Bearer "},
        {"Authorization": "Basic x"},
    ],
)
def test_protected_routes_reject_malformed_credentials(
    client: TestClient, headers: dict[str, str]
) -> None:
    assert client.get("/transactions", headers=headers).status_code in (401, 403)


def test_token_signed_with_a_foreign_secret_is_rejected(client: TestClient) -> None:
    forged = jwt.encode(
        {
            "sub": "1",
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "iss": "pocketwise",
            "jti": "x",
        },
        "a-different-secret-entirely",
        algorithm="HS256",
    )
    assert client.get("/summary", headers=auth(forged)).status_code == 401


def test_unsigned_alg_none_token_is_rejected(client: TestClient) -> None:
    forged = jwt.encode(
        {"sub": "1", "exp": datetime.now(UTC) + timedelta(hours=1)}, key="", algorithm="none"
    )
    assert client.get("/summary", headers=auth(forged)).status_code == 401


def test_expired_token_is_rejected(client: TestClient) -> None:
    expired = jwt.encode(
        {
            "sub": "1",
            "exp": datetime.now(UTC) - timedelta(minutes=1),
            "iss": "pocketwise",
            "jti": "x",
        },
        SECRET,
        algorithm="HS256",
    )
    assert client.get("/summary", headers=auth(expired)).status_code == 401


def test_token_whose_subject_no_longer_exists_is_rejected(client: TestClient) -> None:
    orphan = jwt.encode(
        {
            "sub": "424242",
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "iss": "pocketwise",
            "jti": "x",
        },
        SECRET,
        algorithm="HS256",
    )
    assert client.get("/summary", headers=auth(orphan)).status_code == 401


def test_logout_revokes_the_token_server_side(client: TestClient) -> None:
    headers = auth(register(client))
    assert client.get("/summary", headers=headers).status_code == 200
    assert client.post("/auth/logout", headers=headers).status_code == 204
    assert client.get("/summary", headers=headers).status_code == 401


def test_revocation_denylist_row_is_recorded(db: Session, client: TestClient) -> None:
    headers = auth(register(client))
    client.post("/auth/logout", headers=headers)
    assert db.scalar(select(RevokedToken.jti)) is not None


def test_weak_passwords_are_upgraded_on_login(db: Session, client: TestClient) -> None:
    digest = hashlib.pbkdf2_hmac("sha256", b"password123", b"a1b2c3d4e5f6a7b8", 200_000)
    legacy = f"a1b2c3d4e5f6a7b8${digest.hex()}"
    user = make_user(db, "legacy@example.com")
    user.password_hash = legacy
    db.commit()
    assert needs_rehash(legacy) is True

    response = client.post(
        "/auth/login", json={"email": "legacy@example.com", "password": "password123"}
    )

    assert response.status_code == 200
    db.expire_all()
    refreshed = db.scalar(select(User).where(User.email == "legacy@example.com"))
    assert refreshed is not None
    assert refreshed.password_hash != legacy
    assert needs_rehash(refreshed.password_hash) is False


def test_hash_round_trip_and_corruption_handling() -> None:
    stored = hash_password("password123")
    assert verify_password("password123", stored) is True
    assert verify_password("password124", stored) is False
    assert stored.split("$")[1] == "600000"
    for corrupt in ("", "no-dollar-sign", "pbkdf2_sha256$bad$salt$digest", "a$b$c$d$e"):
        assert verify_password("password123", corrupt) is False
