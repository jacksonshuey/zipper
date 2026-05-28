"""
Zippering — a universal, LLM-assisted schema-reconciliation engine.

Ingest heterogeneous rows from any source. For each incoming column, Zippering
routes it to a canonical column (JOIN an existing one, APPEND a new one, or flag
UNCLEAR for review), normalizes the value to the canonical type, and writes a
wide reconciled row plus an append-only decision audit.

Quickstart
----------
    import asyncio
    from zippering import (
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

from zippering.coercions import UnsafeCoercion, normalize, register_coercer
from zippering.config import Settings
from zippering.engine import (
    ZipperUpsertResult,
    get_decision_history,
    get_zippered_row,
    get_zippered_timeline,
    zipper_upsert,
)
from zippering.lookup import Lookup, LookupVerdict
from zippering.router import AssessInputs, HaikuRouter, Router, assess_column_routing
from zippering.storage import Storage
from zippering.storage_memory import MemoryStorage
from zippering.storage_sqlite import SQLiteStorage
from zippering.types import (
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
    # routing
    "Router",
    "HaikuRouter",
    "AssessInputs",
    "assess_column_routing",
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
