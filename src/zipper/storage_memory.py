"""
In-memory implementation of the Storage protocol.

Zero dependencies, holds everything in plain lists. Ideal for tests,
quickstarts, and notebooks. Not persistent. Each instance is its own isolated
store; all public methods are serialized behind a lock so concurrent
``zipper_upsert`` calls against one instance are safe.
"""

from __future__ import annotations

import functools
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Concatenate, ParamSpec, TypeVar, cast

from zipper.types import (
    GlobalCanonicalColumn,
    ZipperedSignalRow,
    ZipperingDecisionRow,
    ZipperingSchemaRow,
)

_P = ParamSpec("_P")
_R = TypeVar("_R")


def _synchronized(
    method: Callable[Concatenate[MemoryStorage, _P], _R],
) -> Callable[Concatenate[MemoryStorage, _P], _R]:
    """Serialize a MemoryStorage method behind the instance lock."""

    @functools.wraps(method)
    def wrapper(self: MemoryStorage, *args: _P.args, **kwargs: _P.kwargs) -> _R:
        with self._lock:
            return method(self, *args, **kwargs)

    return cast("Callable[Concatenate[MemoryStorage, _P], _R]", wrapper)


def _now_iso() -> str:
    return (
        datetime.now(tz=UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    )


def _new_uuid() -> str:
    return str(uuid.uuid4())


class MemoryStorage:
    """Dict/list-backed Storage. Construct empty; register globals as needed."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._globals: list[GlobalCanonicalColumn] = []
        self._schema: list[ZipperingSchemaRow] = []
        self._decisions: list[ZipperingDecisionRow] = []
        self._signals: list[ZipperedSignalRow] = []

    # -- Reads --------------------------------------------------------------

    @_synchronized
    def load_globals(self, workspace_key: str) -> list[GlobalCanonicalColumn]:
        return [g for g in self._globals if g.workspace_key == workspace_key]

    @_synchronized
    def load_pkey_schema(
        self, workspace_key: str, pkey: str
    ) -> list[ZipperingSchemaRow]:
        return [
            s
            for s in self._schema
            if s.workspace_key == workspace_key and s.pkey == pkey
        ]

    @_synchronized
    def latest_decision_for_column(
        self, workspace_key: str, pkey: str, source: str, source_column: str
    ) -> ZipperingDecisionRow | None:
        matches = [
            d
            for d in self._decisions
            if d.workspace_key == workspace_key
            and d.pkey == pkey
            and d.source == source
            and d.source_column == source_column
        ]
        if not matches:
            return None
        return max(matches, key=lambda d: d.decided_at)

    @_synchronized
    def get_decision_history(
        self, workspace_key: str, pkey: str, canonical_name: str
    ) -> list[ZipperingDecisionRow]:
        matches = [
            d
            for d in self._decisions
            if d.workspace_key == workspace_key
            and d.pkey == pkey
            and d.canonical_name == canonical_name
        ]
        return sorted(matches, key=lambda d: d.decided_at, reverse=True)

    @_synchronized
    def get_zippered_row(
        self, workspace_key: str, pkey: str
    ) -> ZipperedSignalRow | None:
        matches = [
            s
            for s in self._signals
            if s.workspace_key == workspace_key and s.pkey == pkey
        ]
        if not matches:
            return None
        return max(matches, key=lambda s: s.occurred_at)

    @_synchronized
    def get_zippered_timeline(
        self, workspace_key: str, pkey: str, since_iso: str
    ) -> list[ZipperedSignalRow]:
        matches = [
            s
            for s in self._signals
            if s.workspace_key == workspace_key
            and s.pkey == pkey
            and s.occurred_at >= since_iso
        ]
        return sorted(matches, key=lambda s: s.occurred_at, reverse=True)

    # -- Writes -------------------------------------------------------------

    @_synchronized
    def insert_decision(self, decision: dict[str, Any]) -> ZipperingDecisionRow:
        row = ZipperingDecisionRow(
            id=_new_uuid(),
            workspace_key=decision["workspace_key"],
            pkey=decision["pkey"],
            source=decision["source"],
            source_column=decision["source_column"],
            source_data_type=decision.get("source_data_type"),
            source_description=decision.get("source_description"),
            source_samples=decision.get("source_samples"),
            verdict=decision["verdict"],
            canonical_name=decision["canonical_name"],
            is_global_target=bool(decision.get("is_global_target")),
            similarity_score=decision.get("similarity_score"),
            reason=decision.get("reason"),
            needs_review=bool(decision.get("needs_review")),
            decided_by=decision.get("decided_by", "llm"),
            decided_at=decision.get("decided_at") or _now_iso(),
        )
        self._decisions.append(row)
        return row

    @_synchronized
    def upsert_schema_row(self, schema_row: dict[str, Any]) -> None:
        now = _now_iso()
        for i, existing in enumerate(self._schema):
            if (
                existing.workspace_key == schema_row["workspace_key"]
                and existing.pkey == schema_row["pkey"]
                and existing.canonical_name == schema_row["canonical_name"]
            ):
                self._schema[i] = existing.model_copy(
                    update={
                        "data_type": schema_row["data_type"],
                        "description": schema_row.get("description"),
                        "is_global": bool(schema_row.get("is_global")),
                        "source_origin": schema_row.get("source_origin"),
                        "updated_at": now,
                    }
                )
                return
        self._schema.append(
            ZipperingSchemaRow(
                id=_new_uuid(),
                workspace_key=schema_row["workspace_key"],
                pkey=schema_row["pkey"],
                canonical_name=schema_row["canonical_name"],
                data_type=schema_row["data_type"],
                description=schema_row.get("description"),
                is_global=bool(schema_row.get("is_global")),
                source_origin=schema_row.get("source_origin"),
                first_seen_at=now,
                updated_at=now,
            )
        )

    @_synchronized
    def upsert_signal(self, signal: dict[str, Any]) -> str:
        now = _now_iso()
        external_id = signal.get("external_id")
        if external_id is not None:
            for i, existing in enumerate(self._signals):
                if existing.source == signal["source"] and existing.external_id == external_id:
                    self._signals[i] = existing.model_copy(
                        update={
                            "pkey": signal["pkey"],
                            "occurred_at": signal["occurred_at"],
                            "columns": signal.get("columns") or {},
                            "ingested_at": now,
                        }
                    )
                    return existing.id
        row = ZipperedSignalRow(
            id=_new_uuid(),
            workspace_key=signal["workspace_key"],
            pkey=signal["pkey"],
            source=signal["source"],
            external_id=external_id,
            occurred_at=signal["occurred_at"],
            columns=signal.get("columns") or {},
            ingested_at=now,
        )
        self._signals.append(row)
        return row.id

    # -- Convenience --------------------------------------------------------

    @_synchronized
    def add_global_column(
        self,
        name: str,
        data_type: str,
        description: str | None = None,
        semantic_tags: list[str] | None = None,
        workspace_key: str = "default",
    ) -> None:
        """Register a global canonical column (idempotent on name)."""
        if any(
            g.workspace_key == workspace_key and g.name == name for g in self._globals
        ):
            return
        self._globals.append(
            GlobalCanonicalColumn(
                id=_new_uuid(),
                workspace_key=workspace_key,
                name=name,
                data_type=data_type,  # type: ignore[arg-type]
                description=description,
                semantic_tags=semantic_tags or [],
                created_at=_now_iso(),
            )
        )
