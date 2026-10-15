"""Structured audit trail.

Financial deletions and authentication outcomes are recorded with the user id
and source IP only. Passwords and bearer tokens are never logged.
"""

from __future__ import annotations

import logging
import os
import sys

_configured = False

SECURITY_EVENTS = {
    "login_succeeded",
    "login_failed",
    "logout",
    "account_created",
    "token_revoked",
    "transaction_deleted",
    "goal_deleted",
    "rate_limit_exceeded",
}


def configure(level: str | None = None) -> None:
    global _configured
    if _configured:
        return
    resolved = (level or os.getenv("LOG_LEVEL") or "INFO").upper()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s %(message)s", "%Y-%m-%dT%H:%M:%S")
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(resolved)
    audit = logging.getLogger("pocketwise.audit")
    audit.setLevel(logging.INFO)
    audit.propagate = True
    _configured = True


_FAILURES = frozenset({"login_failed", "rate_limit_exceeded"})


def audit(event: str, **fields: object) -> None:
    if event not in SECURITY_EVENTS:
        raise ValueError(f"unknown audit event: {event}")
    logger = logging.getLogger("pocketwise.audit")
    level = logging.WARNING if event in _FAILURES else logging.INFO
    logger.log(level, "%s %s", event, " ".join(f"{k}={v}" for k, v in fields.items()))
