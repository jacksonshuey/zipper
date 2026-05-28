"""
Central configuration for Zippering.

Keeps the Anthropic integration constant across every project that consumes
this package: the model id, the request timeout, and how the API key is
resolved (the ``ANTHROPIC_API_KEY`` environment variable, read by the
Anthropic SDK's default client) all live here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# The routing model. Constant across consumers — override only via Settings.
DEFAULT_MODEL = "claude-haiku-4-5"

# Abort budget for a single routing call (milliseconds). On the hot ingest path.
DEFAULT_TIMEOUT_MS = 8_000

# Token ceiling for the routing call. The tool schema keeps output tiny.
DEFAULT_MAX_TOKENS = 256

# Default workspace partition when a caller does not supply one.
DEFAULT_WORKSPACE_KEY = "default"


@dataclass(frozen=True)
class Settings:
    """Immutable runtime configuration for the engine and router."""

    model: str = DEFAULT_MODEL
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    max_tokens: int = DEFAULT_MAX_TOKENS
    workspace_key: str = DEFAULT_WORKSPACE_KEY
    # When None, the Anthropic SDK reads ANTHROPIC_API_KEY from the environment.
    # Pass an explicit key only when a project must override that default.
    anthropic_api_key: str | None = None

    @classmethod
    def from_env(cls) -> Settings:
        """Build Settings from environment variables, falling back to defaults."""
        return cls(
            model=os.environ.get("ZIPPERING_MODEL", DEFAULT_MODEL),
            timeout_ms=int(os.environ.get("ZIPPERING_TIMEOUT_MS", DEFAULT_TIMEOUT_MS)),
            max_tokens=int(os.environ.get("ZIPPERING_MAX_TOKENS", DEFAULT_MAX_TOKENS)),
            workspace_key=os.environ.get(
                "ZIPPERING_WORKSPACE_KEY", DEFAULT_WORKSPACE_KEY
            ),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
        )
