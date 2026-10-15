"""Password hashing and bearer-token authentication.

Fails closed on misconfiguration: a missing or default SECRET_KEY aborts the
process at import time rather than silently signing tokens with a value that
is published in the repository.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audit
from .database import get_db
from .models import RevokedToken, User

ALGO = "HS256"
ISSUER = "pocketwise"
TOKEN_TTL = timedelta(hours=12)
PBKDF2_ITERATIONS = 600_000
LEGACY_ITERATIONS = 200_000
PBKDF2_PREFIX = "pbkdf2_sha256"
MIN_SECRET_LENGTH = 32

bearer = HTTPBearer(auto_error=False)


def load_secret() -> str:
    raw = os.getenv("SECRET_KEY", "")
    if not raw:
        raise RuntimeError(
            "SECRET_KEY is required. Generate one with: "
            'python -c "import secrets; print(secrets.token_urlsafe(64))"'
        )
    if len(raw) < MIN_SECRET_LENGTH:
        raise RuntimeError(f"SECRET_KEY must be at least {MIN_SECRET_LENGTH} characters")
    return raw


SECRET = load_secret()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ITERATIONS)
    return f"{PBKDF2_PREFIX}${PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def _parse_hash(stored: str) -> tuple[int, str, str] | None:
    parts = stored.split("$")
    if len(parts) == 4 and parts[0] == PBKDF2_PREFIX:
        try:
            return int(parts[1]), parts[2], parts[3]
        except ValueError:
            return None
    if len(parts) == 2:
        return LEGACY_ITERATIONS, parts[0], parts[1]
    return None


def verify_password(password: str, stored: str) -> bool:
    parsed = _parse_hash(stored)
    if parsed is None:
        return False
    iterations, salt, expected = parsed
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations)
    return hmac.compare_digest(digest.hex(), expected)


def needs_rehash(stored: str) -> bool:
    parsed = _parse_hash(stored)
    return parsed is None or parsed[0] < PBKDF2_ITERATIONS


DUMMY_HASH = hash_password(secrets.token_urlsafe(32))


def create_token(user_id: int) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + TOKEN_TTL,
        "iss": ISSUER,
        "jti": secrets.token_urlsafe(16),
    }
    return jwt.encode(payload, SECRET, algorithm=ALGO)


def unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(
            token,
            SECRET,
            algorithms=[ALGO],
            issuer=ISSUER,
            options={"require": ["exp", "sub", "iat", "iss", "jti"]},
        )
    except jwt.PyJWTError:
        raise unauthorized() from None


def current_user(
    cred: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if cred is None:
        raise unauthorized()
    payload = decode_token(cred.credentials)
    revoked = db.scalar(select(RevokedToken.id).where(RevokedToken.jti == payload["jti"]))
    if revoked is not None:
        raise unauthorized()
    try:
        user = db.get(User, int(payload["sub"]))
    except (KeyError, TypeError, ValueError):
        raise unauthorized() from None
    if user is None:
        raise unauthorized()
    return user


def revoke_token(db: Session, token: str) -> None:
    payload = decode_token(token)
    expires = datetime.fromtimestamp(payload["exp"], tz=UTC).replace(tzinfo=None)
    db.add(RevokedToken(jti=payload["jti"], expires_at=expires))
    db.commit()
    audit.audit("token_revoked", user_id=payload["sub"])
