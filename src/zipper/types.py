"""
Pydantic v2 models — the generic Zippering type system.

These mirror the original Dugout TypeScript interfaces. Healthcare/domain
extensions are deliberately NOT included here; the core ships the seven
universal data types and nothing domain-specific. Projects that need extra
types layer them on in their own code.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# String union types
# ---------------------------------------------------------------------------

ZipperingDataType = Literal[
    "text",
    "integer",
    "numeric",
    "boolean",
    "timestamp",
    "jsonb",
    "string[]",
]

ZipperingVerdict = Literal["join", "append", "unclear"]


# ---------------------------------------------------------------------------
# Table row models
# ---------------------------------------------------------------------------


class GlobalCanonicalColumn(BaseModel):
    """Cross-pkey shared field registry row. Maps to global_canonical_columns."""

    id: str
    workspace_key: str
    name: str
    data_type: ZipperingDataType
    description: str | None = None
    semantic_tags: list[str] = Field(default_factory=list)
    created_at: str


class ZipperingSchemaRow(BaseModel):
    """Per-pkey canonical inventory row (mutable). Maps to zippering_schema."""

    id: str
    workspace_key: str
    pkey: str
    canonical_name: str
    data_type: ZipperingDataType
    description: str | None = None
    is_global: bool = False
    source_origin: str | None = None
    first_seen_at: str
    updated_at: str


class ZipperingDecisionRow(BaseModel):
    """Append-only routing/operator audit row. Maps to zippering_decisions."""

    id: str
    workspace_key: str
    pkey: str
    source: str
    source_column: str
    source_data_type: str | None = None
    source_description: str | None = None
    source_samples: list[Any] | None = None
    verdict: ZipperingVerdict
    canonical_name: str
    is_global_target: bool = False
    similarity_score: float | None = None
    reason: str | None = None
    needs_review: bool = False
    decided_by: str  # 'llm' | 'normalizer' | 'lookup' | operator id
    decided_at: str


class ZipperedSignalRow(BaseModel):
    """Wide reconciled row in the zippered store. Maps to zippered_signals."""

    id: str
    workspace_key: str
    pkey: str
    source: str
    external_id: str | None = None
    occurred_at: str
    columns: dict[str, Any] = Field(default_factory=dict)
    ingested_at: str


# ---------------------------------------------------------------------------
# Ingest input models
# ---------------------------------------------------------------------------


class IngestValue(BaseModel):
    """One column's worth of incoming data from a source integration."""

    value: Any
    source_data_type: ZipperingDataType
    source_description: str | None = None


class IngestRow(BaseModel):
    """Input to zipper_upsert(): one incoming integration row."""

    workspace_key: str = "default"
    pkey: str
    source: str
    external_id: str | None = None
    occurred_at: str  # every signal must carry a time
    columns: dict[str, IngestValue]


# ---------------------------------------------------------------------------
# Routing verdict model
# ---------------------------------------------------------------------------


class RoutingVerdict(BaseModel):
    """An LLM router's return shape (enforced via tool_choice + strict schema)."""

    verdict: ZipperingVerdict
    canonical_name: str
    is_global_target: bool
    similarity_score: float
    reason: str
