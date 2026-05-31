"""
Value-normalization seam.

Once routing resolves the canonical target for an incoming column, its value is
normalized to the canonical type. The core ships ``DefaultNormalizer``, which
delegates to the registry-based ``normalize()`` and ignores the target column's
metadata. A consuming project can inject its own ``Normalizer`` to make
context-aware decisions — e.g. converting a lab value into the canonical unit
declared on the target column — without forking the engine.

The injected normalizer receives the already-resolved target rows
(``target_schema`` / ``target_global``) so it can read declared properties
(units, controlled vocabularies, …) straight off the canonical column.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from zipper.coercions import normalize
from zipper.types import GlobalCanonicalColumn, ZipperingSchemaRow


@runtime_checkable
class Normalizer(Protocol):
    """Coerce a source value to its resolved canonical type.

    Implementations MUST raise ``UnsafeCoercion`` when a value cannot be safely
    converted, so the engine routes it to review instead of crashing ingest.
    """

    def normalize(
        self,
        value: Any,
        from_type: str,
        to_type: str,
        *,
        target_schema: ZipperingSchemaRow | None = None,
        target_global: GlobalCanonicalColumn | None = None,
    ) -> Any: ...


class DefaultNormalizer:
    """The core normalizer: registry coercion, ignores target metadata."""

    def normalize(
        self,
        value: Any,
        from_type: str,
        to_type: str,
        *,
        target_schema: ZipperingSchemaRow | None = None,
        target_global: GlobalCanonicalColumn | None = None,
    ) -> Any:
        return normalize(value, from_type, to_type)
