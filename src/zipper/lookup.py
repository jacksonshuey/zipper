"""
Deterministic Tier-1 lookup seam.

The engine consults an optional ``Lookup`` BEFORE the LLM router. A lookup
inspects a column's name and sample values and returns a ``LookupVerdict`` on
a confident, rule-based match — or ``None`` to fall through to the LLM tier.

The core ships NO concrete lookups (no LOINC/RxNorm/etc.) — those are
domain-specific. A consuming project implements this Protocol with its own
registries and injects it into ``zipper_upsert``. Keeping the seam here means
every project wires Tier-1 the same way.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from zipper.types import ZipperingDataType


class LookupVerdict(BaseModel):
    """A confident, rule-based match from the deterministic tier."""

    canonical_column: str
    data_type: ZipperingDataType
    confidence: float = 1.0
    matched_on: str  # free-form: e.g. "column_name", "sample_value"
    reason: str


@runtime_checkable
class Lookup(Protocol):
    """Deterministic matcher consulted before the LLM router."""

    def match(
        self, source_column: str, samples: list[Any]
    ) -> LookupVerdict | None:
        """Return a verdict on a confident match, else None."""
        ...
