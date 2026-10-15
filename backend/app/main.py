"""Application assembly: middleware, error handlers, lifespan, routing.

Schema creation deliberately does NOT live here. `create_all` cannot alter an
existing table, so it silently guarantees the schema is frozen at first boot.
Migrations are applied by Alembic in the container entrypoint instead.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import delete
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import Response

from . import audit
from .database import SessionLocal, engine
from .models import RevokedToken
from .routers import auth_router, ledger_router

VERSION = "1.1.0"
IS_PRODUCTION = os.getenv("ENVIRONMENT", "development").lower() == "production"

log = logging.getLogger("pocketwise")


def _origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", "http://localhost:5173")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def _allowed_hosts() -> list[str] | None:
    raw = os.getenv("ALLOWED_HOSTS", "").strip()
    if not raw:
        return None
    return [host.strip() for host in raw.split(",") if host.strip()]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    audit.configure()
    log.info("pocketwise %s starting (env=%s)", VERSION, os.getenv("ENVIRONMENT", "development"))
    if IS_PRODUCTION:
        purge_expired_tokens()
    yield
    engine.dispose()
    log.info("pocketwise %s stopped", VERSION)


def purge_expired_tokens() -> int:
    """Drop denylist rows whose token has expired anyway, so logout stays
    self-pruning and the table cannot grow without bound."""
    with SessionLocal() as db:
        result = db.execute(delete(RevokedToken).where(RevokedToken.expires_at < datetime.now(UTC)))
        db.commit()
        return result.rowcount or 0


app = FastAPI(
    title="PocketWise API",
    version=VERSION,
    lifespan=lifespan,
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None,
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
    responses={422: {"description": "Validation error"}},
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

_hosts = _allowed_hosts()
if _hosts:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=_hosts)


@app.middleware("http")
async def security_headers(request: Request, call_next: RequestResponseEndpoint) -> Response:
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.url.path.startswith("/auth/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(RequestValidationError)
async def scrub_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    """Rebuild validation errors from an allow-list of fields.

    FastAPI echoes Pydantic's error payload straight back to the client. On
    the auth routes that payload carries `input` -- the plaintext password --
    which would then land in browser history, proxy logs and any API gateway
    in between. `ctx` is dropped for the same reason: a validator's context
    can embed the offending value.
    """
    safe = [
        {key: error[key] for key in ("type", "msg", "loc", "url") if key in error}
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": safe})


@app.get("/health", tags=["ops"])
def health() -> dict[str, str]:
    return {"status": "ok", "version": VERSION}


@app.get("/health/ready", tags=["ops"])
def readiness() -> dict[str, str]:
    """Probe Render's PostgreSQL: the free tier suspends instances, so a
    connection can fail after boot. `/health` stays process-only."""
    with engine.connect() as connection:
        connection.exec_driver_sql("SELECT 1")
    return {"status": "ready"}


app.include_router(auth_router)
app.include_router(ledger_router)
