"""
Zippering — a universal, LLM-assisted schema-reconciliation engine.

Ingest heterogeneous rows from any source. For each incoming column, Zippering
routes it to a canonical column (JOIN an existing one, APPEND a new one, or flag
UNCLEAR for review), normalizes the value to the canonical type, and writes a
wide reconciled row plus an append-only decision audit.

Quickstart
----------
    import asyncio
    from zipper import (
        IngestRow, IngestValue, MemoryStorage, HaikuRouter, zipper_upsert,
    )

    storage = MemoryStorage()
    router = HaikuRouter()  # reads ANTHROPIC_API_KEY from the environment

    row = IngestRow(
        pkey="acct_123",
        source="crm_export",
        occurred_at="2026-05-28T00:00:00Z",
        columns={
            "Company": IngestValue(value="Acme Inc", source_data_type="text"),
            "Headcount": IngestValue(value="240", source_data_type="text"),
        },
    )
    result = asyncio.run(zipper_upsert(row, storage, router))

Pluggable everywhere
--------------------
- Storage   : implement the Storage Protocol (ships MemoryStorage, SQLiteStorage)
- Router    : implement the Router Protocol (ships HaikuRouter — Anthropic)
- Lookup    : optional deterministic Tier-1 (ships the Protocol, no registries)
- Coercions : register_coercer() to add types without forking core
"""

from zipper.coercions import UnsafeCoercion, normalize, register_coercer
from zipper.config import Settings
from zipper.engine import (
    ZipperUpsertResult,
    get_decision_history,
    get_merged_record,
    get_zippered_row,
    get_zippered_timeline,
    zipper_upsert,
)
from zipper.lookup import Lookup, LookupVerdict
from zipper.router import (
    AssessInputs,
    HaikuRouter,
    MissingAPIKeyError,
    Router,
    assess_column_routing,
)
from zipper.storage import Storage
from zipper.storage_memory import MemoryStorage
from zipper.storage_sqlite import SQLiteStorage
from zipper.types import (
    GlobalCanonicalColumn,
    IngestRow,
    IngestValue,
    RoutingVerdict,
    ZipperedSignalRow,
    ZipperingDataType,
    ZipperingDecisionRow,
    ZipperingSchemaRow,
    ZipperingVerdict,
)

__version__ = "0.1.0"

__all__ = [
    # engine
    "zipper_upsert",
    "ZipperUpsertResult",
    "get_zippered_row",
    "get_zippered_timeline",
    "get_decision_history",
    "get_merged_record",
    # routing
    "Router",
    "HaikuRouter",
    "AssessInputs",
    "assess_column_routing",
    "MissingAPIKeyError",
    # lookup
    "Lookup",
    "LookupVerdict",
    # storage
    "Storage",
    "MemoryStorage",
    "SQLiteStorage",
    # coercions
    "normalize",
    "register_coercer",
    "UnsafeCoercion",
    # config
    "Settings",
    # types
    "IngestRow",
    "IngestValue",
    "RoutingVerdict",
    "GlobalCanonicalColumn",
    "ZipperingSchemaRow",
    "ZipperingDecisionRow",
    "ZipperedSignalRow",
    "ZipperingDataType",
    "ZipperingVerdict",
]
