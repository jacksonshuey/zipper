"""
Optional in-process rate limiting for the HTTP API.

A sliding-window limiter keyed by the caller's bearer token (or client host when
the API runs open). Opt-in: set ``ZIPPER_RATE_LIMIT`` to the max requests per
window and, optionally, ``ZIPPER_RATE_WINDOW_S`` (window length in seconds,
default 60). When ``ZIPPER_RATE_LIMIT`` is unset or <= 0, no limiting is
applied, so existing workloads are never throttled by surprise.

Limitation: window state lives in this process only. Behind multiple workers or
instances each holds its own window, so the effective global limit is
``ZIPPER_RATE_LIMIT * worker_count``. For a single shared limit, front the API
with a gateway limiter or a shared store (e.g. Redis).
"""

from __future__ import annotations

import hashlib
import math
import os
import threading
import time
from collections import deque

try:
    from fastapi import Header, HTTPException, Request, status
except ModuleNotFoundError as exc:  # pragma: no cover
    raise ModuleNotFoundError(
        'The HTTP API requires the "api" extra. Install with: '
        'pip install "zipper[api]"'
    ) from exc

from zipper.auth import _extract_bearer

_lock = threading.Lock()
_hits: dict[str, deque[float]] = {}


def _now() -> float:
    """Monotonic clock seam — overridable in tests."""
    return time.monotonic()


def _limit() -> int:
    try:
        return int(os.environ.get("ZIPPER_RATE_LIMIT", "0"))
    except ValueError:
        return 0


def _window_s() -> float:
    try:
        window = float(os.environ.get("ZIPPER_RATE_WINDOW_S", "60"))
    except ValueError:
        return 60.0
    return window if window > 0 else 60.0


def _caller_key(authorization: str | None, request: Request) -> str:
    token = _extract_bearer(authorization)
    if token:
        # Hash so raw tokens never sit in the long-lived counter dict.
        return "tok:" + hashlib.sha256(token.encode()).hexdigest()
    host = request.client.host if request.client else "unknown"
    return "ip:" + host


def reset() -> None:
    """Clear all windows. Used by tests."""
    with _lock:
        _hits.clear()


def enforce_rate_limit(
    request: Request, authorization: str | None = Header(default=None)
) -> None:
    """FastAPI dependency: throttle per caller when a limit is configured."""
    limit = _limit()
    if limit <= 0:
        return
    window = _window_s()
    key = _caller_key(authorization, request)
    now = _now()
    cutoff = now - window
    with _lock:
        bucket = _hits.get(key)
        if bucket is None:
            bucket = deque()
            _hits[key] = bucket
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            retry_after = max(1, math.ceil(bucket[0] + window - now))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="rate limit exceeded",
                headers={"Retry-After": str(retry_after)},
            )
        bucket.append(now)
