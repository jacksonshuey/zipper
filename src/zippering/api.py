"""
Optional HTTP API for Zippering (FastAPI).

Exposes the engine over HTTP so non-Python projects can use the zipper method
too. Install the ``api`` extra:  pip install "zippering[api]"

Run:
    uvicorn zippering.api:app --reload

A single process-wide SQLiteStorage and HaikuRouter are created at startup.
Set ZIPPERING_DB_PATH to persist (default: in-memory). The router reads
ANTHROPIC_API_KEY from the environment, exactly like the library.
"""

from __future__ import annotations

import os
from typing import Any

try:
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel
except ModuleNotFoundError as exc:  # pragma: no cover
    raise ModuleNotFoundError(
        'The HTTP API requires the "api" extra. Install with: '
        'pip install "zippering[api]"'
    ) from exc

from zippering.engine import (
    get_decision_history,
    get_zippered_row,
    get_zippered_timeline,
    zipper_upsert,
)
from zippering.router import HaikuRouter
from zippering.storage_sqlite import SQLiteStorage
from zippering.types import (
    IngestRow,
    ZipperedSignalRow,
    ZipperingDecisionRow,
)

app = FastAPI(title="Zippering", version="0.1.0")

_storage = SQLiteStorage(os.environ.get("ZIPPERING_DB_PATH", ":memory:"))
_router = HaikuRouter()


class UpsertResponse(BaseModel):
    signal_id: str
    decisions: list[ZipperingDecisionRow]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/ingest", response_model=UpsertResponse)
async def ingest(row: IngestRow) -> UpsertResponse:
    """Ingest one source row through the zipper method."""
    result = await zipper_upsert(row, _storage, _router)
    return UpsertResponse(signal_id=result.signal_id, decisions=result.decisions)


@app.get("/v1/signals/{workspace_key}/{pkey}", response_model=ZipperedSignalRow)
async def latest_signal(workspace_key: str, pkey: str) -> ZipperedSignalRow:
    """Most recent reconciled row for (workspace_key, pkey)."""
    signal = await get_zippered_row(workspace_key, pkey, _storage)
    if signal is None:
        raise HTTPException(status_code=404, detail="no signal for this pkey")
    return signal


@app.get("/v1/timeline/{workspace_key}/{pkey}")
async def timeline(
    workspace_key: str, pkey: str, since: str
) -> list[ZipperedSignalRow]:
    """All reconciled rows for (workspace_key, pkey) since an ISO timestamp."""
    return await get_zippered_timeline(workspace_key, pkey, since, _storage)


@app.get("/v1/decisions/{workspace_key}/{pkey}/{canonical_name}")
async def decisions(
    workspace_key: str, pkey: str, canonical_name: str
) -> list[ZipperingDecisionRow]:
    """Append-only routing audit for one canonical column."""
    return await get_decision_history(workspace_key, pkey, canonical_name, _storage)


def register_global_column(payload: dict[str, Any]) -> None:  # pragma: no cover
    """Helper used by tests/scripts to seed a global canonical column."""
    _storage.add_global_column(**payload)
