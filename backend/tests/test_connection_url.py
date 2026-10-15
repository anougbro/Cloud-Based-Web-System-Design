"""Regression tests for connection-string derivation.

The motivation is a defect that shipped and then had to be fixed: Alembic
derived its connection string with `str(engine.url)`, which renders the
password as `***`. Every migration against PostgreSQL failed with
"password authentication failed", while the whole test suite stayed green
because it only ever runs against SQLite -- a backend that has no password.

These tests pin both the trap and the fix, so the mistake cannot come back
unnoticed.
"""

from __future__ import annotations

from configparser import ConfigParser

from sqlalchemy import URL, create_engine
from sqlalchemy.engine import make_url

from app.database import migration_url, normalise_url

# A password containing every character that matters in a URL. Built through
# SQLAlchemy's URL.create so the driver percent-encodes it exactly as it does
# for a real DATABASE_URL; hand-writing the encoded form here would test the
# test rather than the code.
CREDENTIALS = {
    "drivername": "postgresql",
    "username": "pocketwise_user",
    "password": "p@ss:w/rd?#%",
    "host": "db-host",
    "port": 5432,
    "database": "pocketwise",
}

RAW_URL = "postgresql://pocketwise_user:postgres://weird@host/db"


def postgres_engine():
    return create_engine(URL.create(**CREDENTIALS))


def test_str_of_a_url_masks_the_password() -> None:
    """Document the trap itself.

    If this ever stops holding -- SQLAlchemy changed its rendering -- then
    `str(engine.url)` stops being a bug and the workaround in migration_url
    becomes unnecessary. The test says so rather than leaving the assumption
    buried in a comment.
    """
    assert "***" in str(postgres_engine().url)
    assert "p@ss" not in str(postgres_engine().url)


def test_migration_url_preserves_the_password() -> None:
    """The regression: migrations must connect with the real password."""
    rendered = migration_url(postgres_engine())

    assert "***" not in rendered
    assert "pocketwise_user" in rendered
    assert "db-host" in rendered
    assert "5432" in rendered
    # Every special character is percent-encoded rather than dropped.
    assert "%40" in rendered  # @
    assert "%3A" in rendered  # :
    assert "%2F" in rendered  # /
    assert "%25" in rendered  # %


def test_migration_url_round_trips_through_configparser() -> None:
    """Alembic reads the URL through ConfigParser, where `%` is interpolation.

    A literal `%` in the password has to survive the double-then-single
    unescaping, or the password arrives at the driver altered.
    """
    parser = ConfigParser()
    parser.read_dict({"sqlalchemy": {"url": migration_url(postgres_engine())}})
    recovered = parser.get("sqlalchemy", "url")

    assert "***" not in recovered

    # The recovered string is what SQLAlchemy parses, so re-parsing it must
    # recover the original password byte for byte.
    assert make_url(recovered).password == CREDENTIALS["password"]


def test_migration_url_is_stable_for_sqlite() -> None:
    """SQLite has no password, and the fallback must not break it."""
    engine = create_engine("sqlite:///./test.db")
    rendered = migration_url(engine)
    assert rendered.startswith("sqlite:///")
    assert "***" not in rendered


def test_normalise_url_rewrites_render_legacy_prefixes() -> None:
    """Render still hands out `postgres://`, which SQLAlchemy 2 rejects."""
    assert normalise_url("postgres://u:p@h/db").startswith("postgresql://")
    assert normalise_url("postgres+psycopg2://u:p@h/db").startswith("postgresql://")
    # A URL that is already correct is returned untouched.
    assert normalise_url(RAW_URL) == RAW_URL


def test_normalise_url_does_not_touch_the_password() -> None:
    """Rewriting the scheme must not disturb credentials.

    Uses `replace` with a count on the prefix only; a looser replacement
    would rewrite the password too if it happened to contain the string.
    """
    url = "postgres://user:postgres://weird@host/db"
    out = normalise_url(url)
    assert out == "postgresql://user:postgres://weird@host/db"
