"""
SQLite implementation of the Storage protocol.

Stdlib sqlite3 only — no ORM. JSON columns are stored as TEXT and round-tripped
via json.dumps/loads. UUIDs are generated in Python. The bundled schema.sql is
applied automatically on construction.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import Any

from zipper.types import (
    GlobalCanonicalColumn,
    ZipperedSignalRow,
    ZipperingDecisionRow,
    ZipperingSchemaRow,
)


def _now_iso() -> str:
    return (
        datetime.now(tz=UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    )


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _load_schema_sql() -> str:
    return resources.files("zipper").joinpath("schema.sql").read_text()


def _row_to_global(row: sqlite3.Row) -> GlobalCanonicalColumn:
    tags = json.loads(row["semantic_tags"]) if row["semantic_tags"] else []
    return GlobalCanonicalColumn(
        id=row["id"],
        workspace_key=row["workspace_key"],
        name=row["name"],
        data_type=row["data_type"],
        description=row["description"],
        semantic_tags=tags,
        created_at=row["created_at"],
    )


def _row_to_schema(row: sqlite3.Row) -> ZipperingSchemaRow:
    return ZipperingSchemaRow(
        id=row["id"],
        workspace_key=row["workspace_key"],
        pkey=row["pkey"],
        canonical_name=row["canonical_name"],
        data_type=row["data_type"],
        description=row["description"],
        is_global=bool(row["is_global"]),
        source_origin=row["source_origin"],
        first_seen_at=row["first_seen_at"],
        updated_at=row["updated_at"],
    )


def _row_to_decision(row: sqlite3.Row) -> ZipperingDecisionRow:
    samples = json.loads(row["source_samples"]) if row["source_samples"] else None
    return ZipperingDecisionRow(
        id=row["id"],
        workspace_key=row["workspace_key"],
        pkey=row["pkey"],
        source=row["source"],
        source_column=row["source_column"],
        source_data_type=row["source_data_type"],
        source_description=row["source_description"],
        source_samples=samples,
        verdict=row["verdict"],
        canonical_name=row["canonical_name"],
        is_global_target=bool(row["is_global_target"]),
        similarity_score=row["similarity_score"],
        reason=row["reason"],
        needs_review=bool(row["needs_review"]),
        decided_by=row["decided_by"],
        decided_at=row["decided_at"],
    )


def _row_to_signal(row: sqlite3.Row) -> ZipperedSignalRow:
    cols = json.loads(row["columns"]) if row["columns"] else {}
    return ZipperedSignalRow(
        id=row["id"],
        workspace_key=row["workspace_key"],
        pkey=row["pkey"],
        source=row["source"],
        external_id=row["external_id"],
        occurred_at=row["occurred_at"],
        columns=cols,
        ingested_at=row["ingested_at"],
    )


class SQLiteStorage:
    """
    SQLite-backed Storage. Pass ``:memory:`` (default) for an ephemeral store
    or a file path for persistence. The schema is applied on construction.
    """

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_load_schema_sql())

    def apply_migration(self, sql: str) -> None:
        """Execute an additional SQL script (idempotent via IF NOT EXISTS)."""
        self._conn.executescript(sql)

    # -- Reads --------------------------------------------------------------

    def load_globals(self, workspace_key: str) -> list[GlobalCanonicalColumn]:
        cur = self._conn.execute(
            "SELECT * FROM global_canonical_columns WHERE workspace_key = ?",
            (workspace_key,),
        )
        return [_row_to_global(r) for r in cur.fetchall()]

    def load_pkey_schema(
        self, workspace_key: str, pkey: str
    ) -> list[ZipperingSchemaRow]:
        cur = self._conn.execute(
            "SELECT * FROM zippering_schema WHERE workspace_key = ? AND pkey = ?",
            (workspace_key, pkey),
        )
        return [_row_to_schema(r) for r in cur.fetchall()]

    def latest_decision_for_column(
        self, workspace_key: str, pkey: str, source: str, source_column: str
    ) -> ZipperingDecisionRow | None:
        cur = self._conn.execute(
            "SELECT * FROM zippering_decisions "
            "WHERE workspace_key = ? AND pkey = ? AND source = ? AND source_column = ? "
            "ORDER BY decided_at DESC LIMIT 1",
            (workspace_key, pkey, source, source_column),
        )
        row = cur.fetchone()
        return _row_to_decision(row) if row else None

    def get_decision_history(
        self, workspace_key: str, pkey: str, canonical_name: str
    ) -> list[ZipperingDecisionRow]:
        cur = self._conn.execute(
            "SELECT * FROM zippering_decisions "
            "WHERE workspace_key = ? AND pkey = ? AND canonical_name = ? "
            "ORDER BY decided_at DESC",
            (workspace_key, pkey, canonical_name),
        )
        return [_row_to_decision(r) for r in cur.fetchall()]

    def get_zippered_row(
        self, workspace_key: str, pkey: str
    ) -> ZipperedSignalRow | None:
        cur = self._conn.execute(
            "SELECT * FROM zippered_signals "
            "WHERE workspace_key = ? AND pkey = ? ORDER BY occurred_at DESC LIMIT 1",
            (workspace_key, pkey),
        )
        row = cur.fetchone()
        return _row_to_signal(row) if row else None

    def get_zippered_timeline(
        self, workspace_key: str, pkey: str, since_iso: str
    ) -> list[ZipperedSignalRow]:
        cur = self._conn.execute(
            "SELECT * FROM zippered_signals "
            "WHERE workspace_key = ? AND pkey = ? AND occurred_at >= ? "
            "ORDER BY occurred_at DESC",
            (workspace_key, pkey, since_iso),
        )
        return [_row_to_signal(r) for r in cur.fetchall()]

    # -- Writes -------------------------------------------------------------

    def insert_decision(self, decision: dict[str, Any]) -> ZipperingDecisionRow:
        row_id = _new_uuid()
        decided_at = decision.get("decided_at") or _now_iso()
        samples = decision.get("source_samples")
        samples_json = json.dumps(samples) if samples is not None else None

        self._conn.execute(
            """
            INSERT INTO zippering_decisions (
                id, workspace_key, pkey, source, source_column,
                source_data_type, source_description, source_samples,
                verdict, canonical_name, is_global_target, similarity_score,
                reason, needs_review, decided_by, decided_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                row_id,
                decision["workspace_key"],
                decision["pkey"],
                decision["source"],
                decision["source_column"],
                decision.get("source_data_type"),
                decision.get("source_description"),
                samples_json,
                decision["verdict"],
                decision["canonical_name"],
                1 if decision.get("is_global_target") else 0,
                decision.get("similarity_score"),
                decision.get("reason"),
                1 if decision.get("needs_review") else 0,
                decision.get("decided_by", "llm"),
                decided_at,
            ),
        )
        self._conn.commit()
        row = self._conn.execute(
            "SELECT * FROM zippering_decisions WHERE id = ?", (row_id,)
        ).fetchone()
        return _row_to_decision(row)

    def upsert_schema_row(self, schema_row: dict[str, Any]) -> None:
        row_id = _new_uuid()
        now = _now_iso()
        self._conn.execute(
            """
            INSERT INTO zippering_schema (
                id, workspace_key, pkey, canonical_name, data_type,
                description, is_global, source_origin, first_seen_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(workspace_key, pkey, canonical_name) DO UPDATE SET
                data_type     = excluded.data_type,
                description   = excluded.description,
                is_global     = excluded.is_global,
                source_origin = excluded.source_origin,
                updated_at    = excluded.updated_at
            """,
            (
                row_id,
                schema_row["workspace_key"],
                schema_row["pkey"],
                schema_row["canonical_name"],
                schema_row["data_type"],
                schema_row.get("description"),
                1 if schema_row.get("is_global") else 0,
                schema_row.get("source_origin"),
                now,
                now,
            ),
        )
        self._conn.commit()

    def upsert_signal(self, signal: dict[str, Any]) -> str:
        cols_json = json.dumps(signal.get("columns") or {})
        now = _now_iso()
        external_id = signal.get("external_id")
        existing_id: str | None = None

        if external_id is not None:
            row = self._conn.execute(
                "SELECT id FROM zippered_signals WHERE source = ? AND external_id = ?",
                (signal["source"], external_id),
            ).fetchone()
            if row:
                existing_id = row["id"]

        if existing_id is not None:
            self._conn.execute(
                "UPDATE zippered_signals "
                "SET pkey=?, occurred_at=?, columns=?, ingested_at=? WHERE id=?",
                (signal["pkey"], signal["occurred_at"], cols_json, now, existing_id),
            )
            self._conn.commit()
            return existing_id

        row_id = _new_uuid()
        self._conn.execute(
            """
            INSERT INTO zippered_signals (
                id, workspace_key, pkey, source, external_id,
                occurred_at, columns, ingested_at
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                row_id,
                signal["workspace_key"],
                signal["pkey"],
                signal["source"],
                external_id,
                signal["occurred_at"],
                cols_json,
                now,
            ),
        )
        self._conn.commit()
        return row_id

    def add_global_column(
        self,
        name: str,
        data_type: str,
        description: str | None = None,
        semantic_tags: list[str] | None = None,
        workspace_key: str = "default",
    ) -> None:
        """Convenience: register a global canonical column (idempotent on name)."""
        self._conn.execute(
            """
            INSERT OR IGNORE INTO global_canonical_columns
                (id, workspace_key, name, data_type, description, semantic_tags, created_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                _new_uuid(),
                workspace_key,
                name,
                data_type,
                description,
                json.dumps(semantic_tags or []),
                _now_iso(),
            ),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
