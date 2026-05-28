"""
Optional bearer-token authentication for the HTTP API.

The library is bring-your-own-key and the HTTP API is a convenience layer, so
auth here is deliberately small: a static set of client tokens supplied via the
``ZIPPER_API_KEYS`` environment variable (comma-separated). A request to a
protected route must send ``Authorization: Bearer <token>`` matching one of
them. Tokens are compared in constant time and never logged or persisted.

Secure by default: if no keys are configured the protected routes return 503
rather than serving open, unless you explicitly opt out with
``ZIPPER_ALLOW_NO_AUTH=1`` (for when the API already sits behind your own
gateway or auth proxy).
"""

from __future__ import annotations

import os
import secrets

try:
    from fastapi import Header, HTTPException, status
except ModuleNotFoundError as exc:  # pragma: no cover
    raise ModuleNotFoundError(
        'The HTTP API requires the "api" extra. Install with: '
        'pip install "zipper[api]"'
    ) from exc

_TRUTHY = {"1", "true", "yes", "on"}


def configured_keys() -> frozenset[str]:
    """The set of accepted client tokens, parsed from ``ZIPPER_API_KEYS``."""
    raw = os.environ.get("ZIPPER_API_KEYS", "")
    return frozenset(token.strip() for token in raw.split(",") if token.strip())


def allow_no_auth() -> bool:
    """Whether the operator has explicitly opted out of auth."""
    return os.environ.get("ZIPPER_ALLOW_NO_AUTH", "").strip().lower() in _TRUTHY


def _extract_bearer(header: str | None) -> str | None:
    if not header:
        return None
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer":
        return None
    token = token.strip()
    return token or None


def _matches(token: str, keys: frozenset[str]) -> bool:
    # Constant-time compare against every configured key (no early exit).
    return any(secrets.compare_digest(token, key) for key in keys)


def require_auth(authorization: str | None = Header(default=None)) -> None:
    """FastAPI dependency: reject requests without a valid bearer token.

    Returns ``None`` (allow) when the caller is authorized; otherwise raises an
    ``HTTPException`` (401 for a bad/missing token, 503 when auth is not
    configured and not explicitly disabled).
    """
    keys = configured_keys()
    if not keys:
        if allow_no_auth():
            return
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "API authentication is not configured. Set ZIPPER_API_KEYS "
                "(comma-separated client tokens), or set ZIPPER_ALLOW_NO_AUTH=1 "
                "to run open behind your own gateway."
            ),
        )
    token = _extract_bearer(authorization)
    if token is None or not _matches(token, keys):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
