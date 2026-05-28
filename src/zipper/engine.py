"""
Zippering ingest engine.

The "zipper method": ingest one heterogeneous source row, route each incoming
column to a canonical column (JOIN / APPEND / UNCLEAR), normalize its value,
and write a wide reconciled row plus an append-only decision audit.

Hot path:  zipper_upsert(row, storage, router, lookup=None)
Read path: get_zippered_row / get_zippered_timeline / get_decision_history

Routing tiers (in order):
  1. Cache  — reuse the latest decision for (pkey, source, source_column).
  2. Lookup — optional deterministic Tier-1 (injected; core ships none).
  3. Router — LLM semantic match (JOIN existing / APPEND new / UNCLEAR).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from zipper.coercions import UnsafeCoercion, normalize
from zipper.lookup import Lookup
from zipper.router import AssessInputs, Router
from zipper.storage import Storage
from zipper.types import (
    IngestRow,
    ZipperedSignalRow,
    ZipperingDataType,
    ZipperingDecisionRow,
)


@dataclass
class ZipperUpsertResult:
    """Return value of zipper_upsert()."""

    signal_id: str
    decisions: list[ZipperingDecisionRow]


async def zipper_upsert(
    row: IngestRow,
    storage: Storage,
    router: Router,
    lookup: Lookup | None = None,
) -> ZipperUpsertResult:
    """Ingest one source row into the zippering pipeline."""
    workspace_key = row.workspace_key

    globals_list, existing_schema = await asyncio.gather(
        asyncio.to_thread(storage.load_globals, workspace_key),
        asyncio.to_thread(storage.load_pkey_schema, workspace_key, row.pkey),
    )

    all_decisions: list[ZipperingDecisionRow] = []
    canonical_columns: dict[str, Any] = {}

    for source_col, ingest_val in row.columns.items():
        cached_decision = await asyncio.to_thread(
            storage.latest_decision_for_column,
            workspace_key,
            row.pkey,
            row.source,
            source_col,
        )

        decision: ZipperingDecisionRow
        samples: list[Any] = (
            [ingest_val.value] if ingest_val.value is not None else []
        )

        if cached_decision is not None:
            # Tier 1: cache hit — reuse existing routing.
            decision = cached_decision
        else:
            lookup_verdict = lookup.match(source_col, samples) if lookup else None

            if lookup_verdict is not None:
                # Tier 2: deterministic lookup.
                decision = await asyncio.to_thread(
                    storage.insert_decision,
                    {
                        "workspace_key": workspace_key,
                        "pkey": row.pkey,
                        "source": row.source,
                        "source_column": source_col,
                        "source_data_type": ingest_val.source_data_type,
                        "source_description": ingest_val.source_description,
                        "source_samples": samples or None,
                        "verdict": "join",
                        "canonical_name": lookup_verdict.canonical_column,
                        "is_global_target": False,
                        "similarity_score": lookup_verdict.confidence,
                        "reason": lookup_verdict.reason,
                        "needs_review": False,
                        "decided_by": "lookup",
                    },
                )
                await asyncio.to_thread(
                    storage.upsert_schema_row,
                    {
                        "workspace_key": workspace_key,
                        "pkey": row.pkey,
                        "canonical_name": lookup_verdict.canonical_column,
                        "data_type": lookup_verdict.data_type,
                        "description": ingest_val.source_description,
                        "is_global": False,
                        "source_origin": row.source,
                    },
                )
            else:
                # Tier 3: LLM router.
                verdict = await router.assess(
                    AssessInputs(
                        pkey=row.pkey,
                        source=row.source,
                        source_column=source_col,
                        source_data_type=ingest_val.source_data_type,
                        source_description=ingest_val.source_description,
                        source_samples=samples,
                        candidates_global=globals_list,
                        candidates_pkey=existing_schema,
                    )
                )
                decision = await asyncio.to_thread(
                    storage.insert_decision,
                    {
                        "workspace_key": workspace_key,
                        "pkey": row.pkey,
                        "source": row.source,
                        "source_column": source_col,
                        "source_data_type": ingest_val.source_data_type,
                        "source_description": ingest_val.source_description,
                        "source_samples": samples or None,
                        "verdict": verdict.verdict,
                        "canonical_name": verdict.canonical_name,
                        "is_global_target": verdict.is_global_target,
                        "similarity_score": verdict.similarity_score,
                        "reason": verdict.reason,
                        "needs_review": verdict.verdict == "unclear",
                        "decided_by": "llm",
                    },
                )

                if verdict.verdict in ("append", "unclear", "join"):
                    if verdict.is_global_target:
                        global_match = next(
                            (
                                g
                                for g in globals_list
                                if g.name == verdict.canonical_name
                            ),
                            None,
                        )
                        canonical_data_type: ZipperingDataType = (
                            global_match.data_type
                            if global_match is not None
                            else ingest_val.source_data_type
                        )
                    else:
                        canonical_data_type = ingest_val.source_data_type

                    await asyncio.to_thread(
                        storage.upsert_schema_row,
                        {
                            "workspace_key": workspace_key,
                            "pkey": row.pkey,
                            "canonical_name": verdict.canonical_name,
                            "data_type": canonical_data_type,
                            "description": ingest_val.source_description,
                            "is_global": verdict.is_global_target,
                            "source_origin": row.source,
                        },
                    )

        all_decisions.append(decision)

        # Resolve the canonical target type, then normalize.
        schema_match = next(
            (s for s in existing_schema if s.canonical_name == decision.canonical_name),
            None,
        )
        global_match = next(
            (g for g in globals_list if g.name == decision.canonical_name),
            None,
        )
        target_data_type: ZipperingDataType = (
            schema_match.data_type
            if schema_match is not None
            else (
                global_match.data_type
                if global_match is not None
                else ingest_val.source_data_type
            )
        )

        try:
            normalized_value = normalize(
                ingest_val.value, ingest_val.source_data_type, target_data_type
            )
            canonical_columns[decision.canonical_name] = normalized_value
        except UnsafeCoercion as err:
            # Append a needs_review row (never update) and skip the value.
            review = await asyncio.to_thread(
                storage.insert_decision,
                {
                    "workspace_key": workspace_key,
                    "pkey": row.pkey,
                    "source": row.source,
                    "source_column": source_col,
                    "source_data_type": ingest_val.source_data_type,
                    "source_description": ingest_val.source_description,
                    "source_samples": samples or None,
                    "verdict": decision.verdict,
                    "canonical_name": decision.canonical_name,
                    "is_global_target": decision.is_global_target,
                    "similarity_score": decision.similarity_score,
                    "reason": str(err),
                    "needs_review": True,
                    "decided_by": "normalizer",
                },
            )
            all_decisions.append(review)

    signal_id = await asyncio.to_thread(
        storage.upsert_signal,
        {
            "workspace_key": workspace_key,
            "pkey": row.pkey,
            "source": row.source,
            "external_id": row.external_id,
            "occurred_at": row.occurred_at,
            "columns": canonical_columns,
        },
    )

    return ZipperUpsertResult(signal_id=signal_id, decisions=all_decisions)


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------


async def get_zippered_row(
    workspace_key: str, pkey: str, storage: Storage
) -> ZipperedSignalRow | None:
    """Most recent zippered signal row for (workspace, pkey). None if empty."""
    return await asyncio.to_thread(storage.get_zippered_row, workspace_key, pkey)


async def get_zippered_timeline(
    workspace_key: str, pkey: str, since_iso: str, storage: Storage
) -> list[ZipperedSignalRow]:
    """All zippered rows for (workspace, pkey) since since_iso, occurred_at DESC."""
    return await asyncio.to_thread(
        storage.get_zippered_timeline, workspace_key, pkey, since_iso
    )


async def get_decision_history(
    workspace_key: str, pkey: str, canonical_name: str, storage: Storage
) -> list[ZipperingDecisionRow]:
    """Full append-only decision history for a canonical slice."""
    return await asyncio.to_thread(
        storage.get_decision_history, workspace_key, pkey, canonical_name
    )
