"""In-memory sliding-window rate limiting, keyed by client IP.

Bounded and thread-safe. The state lives in the process, so it resets on
restart and is per-instance: correct for the single-instance deployment this
project ships with. Scaling past one instance requires a shared store (Redis)
behind the same interface.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from . import audit


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float, *, name: str) -> None:
        self.limit = limit
        self.window = window_seconds
        self.name = name
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        bucket = self._hits[key]
        cutoff = now - self.window
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        return bucket

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            for stale in [k for k, v in self._hits.items() if not self._prune(k, now)]:
                del self._hits[stale]
            bucket = self._prune(key, now)
            if len(bucket) >= self.limit:
                retry_after = int(self.window - (now - bucket[0])) + 1
                audit.audit("rate_limit_exceeded", scope=self.name, key=key)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Too many {self.name} attempts. Retry in {retry_after}s.",
                    headers={"Retry-After": str(retry_after)},
                )
            bucket.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


login_limiter = SlidingWindowLimiter(limit=10, window_seconds=900, name="login")
register_limiter = SlidingWindowLimiter(limit=5, window_seconds=3600, name="registration")


def client_key(request: Request) -> str:
    host = request.client.host if request.client else "unknown"
    return f"{host}:{request.url.path}"


def enforce(limiter: SlidingWindowLimiter, request: Request) -> None:
    limiter.check(client_key(request))
