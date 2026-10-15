from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import audit, queries
from ..database import get_db
from ..models import User
from ..rate_limit import enforce, login_limiter, register_limiter
from ..schemas import Credentials, TokenOut
from ..security import (
    DUMMY_HASH,
    TOKEN_TTL,
    create_token,
    current_user,
    hash_password,
    needs_rehash,
    revoke_token,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])

DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(current_user)]


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def register(request: Request, body: Credentials, db: DbSession) -> TokenOut:
    """Create an account and return a bearer token immediately.

    Duplicate detection runs twice on purpose: the read gives a cheap 409 for
    the common case, the IntegrityError catch closes the race where two
    concurrent registrations pass the read and collide on the unique index.
    """
    enforce(register_limiter, request)
    email = body.email.lower()
    if queries.find_user_by_email(db, email) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    user = User(email=email, password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered") from None
    db.refresh(user)
    audit.audit("account_created", user_id=user.id, ip=_ip(request))
    return TokenOut(access_token=create_token(user.id), expires_in=int(TOKEN_TTL.total_seconds()))


@router.post("/login", response_model=TokenOut)
def login(request: Request, body: Credentials, db: DbSession) -> TokenOut:
    """Verify credentials without leaking account existence through timing.

    The password hash is computed even when the email is unknown, so both
    branches take the same ~1 iteration cost. Otherwise the response latency
    is a 20x oracle for enumerating registered addresses.
    """
    enforce(login_limiter, request)
    user = queries.find_user_by_email(db, body.email.lower())
    verified = verify_password(body.password, user.password_hash if user else DUMMY_HASH)
    if user is None or not verified:
        audit.audit("login_failed", email=body.email.lower(), ip=_ip(request))
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
        db.commit()
    audit.audit("login_succeeded", user_id=user.id, ip=_ip(request))
    return TokenOut(access_token=create_token(user.id), expires_in=int(TOKEN_TTL.total_seconds()))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, user: CurrentUser, db: DbSession) -> None:
    """Denylist the presented token until its natural expiry.

    Without this, a stolen bearer token stays valid for the full TTL and
    client-side logout has no effect the server can observe.
    """
    header = request.headers.get("Authorization", "")
    token = header.removeprefix("Bearer ").strip()
    if token:
        revoke_token(db, token)
        audit.audit("logout", user_id=user.id, ip=_ip(request))
