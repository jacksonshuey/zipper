"""
Storage Protocol — the persistence contract for the Zippering engine.

This decouples the engine from any specific backend. The package ships an
in-memory implementation (zero dependencies, great for tests and quickstarts)
and a SQLite implementation. A project can add Postgres/Snowflake/etc. by
satisfying this Protocol — the engine never changes.

All methods are synchronous. The engine runs them from async context via
``asyncio.to_thread`` so blocking drivers stay simple.

Hard invariant: ``insert_decision`` MUST be INSERT-only. The decision log is
append-only — operator overrides and normalizer flags add NEW rows; nothing is
ever updated in place.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from zippering.types import (
    GlobalCanonicalColumn,
    ZipperedSignalRow,
    ZipperingDecisionRow,
    ZipperingSchemaRow,
)


@runtime_checkable
class Storage(Protocol):
    """Persistence contract for the Zippering engine."""

    # -- Reads --------------------------------------------------------------

    def load_globals(self, workspace_key: str) -> list[GlobalCanonicalColumn]:
        """Return all global_canonical_columns for the workspace."""
        ...

    def load_pkey_schema(
        self, workspace_key: str, pkey: str
    ) -> list[ZipperingSchemaRow]:
        """Return all zippering_schema rows for (workspace_key, pkey)."""
        ...

    def latest_decision_for_column(
        self, workspace_key: str, pkey: str, source: str, source_column: str
    ) -> ZipperingDecisionRow | None:
        """Most recent decision for the quad, by decided_at DESC. None on miss."""
        ...

    def get_decision_history(
        self, workspace_key: str, pkey: str, canonical_name: str
    ) -> list[ZipperingDecisionRow]:
        """Full audit history for a canonical slice, decided_at DESC."""
        ...

    def get_zippered_row(
        self, workspace_key: str, pkey: str
    ) -> ZipperedSignalRow | None:
        """Most recent zippered_signals row for (workspace_key, pkey)."""
        ...

    def get_zippered_timeline(
        self, workspace_key: str, pkey: str, since_iso: str
    ) -> list[ZipperedSignalRow]:
        """All zippered_signals rows since since_iso, occurred_at DESC."""
        ...

    # -- Writes -------------------------------------------------------------

    def insert_decision(self, decision: dict[str, Any]) -> ZipperingDecisionRow:
        """INSERT a decision row and return it. MUST be insert-only."""
        ...

    def upsert_schema_row(self, schema_row: dict[str, Any]) -> None:
        """UPSERT on (workspace_key, pkey, canonical_name)."""
        ...

    def upsert_signal(self, signal: dict[str, Any]) -> str:
        """UPSERT on (source, external_id). Returns the row id."""
        ...
