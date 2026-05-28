"""
Write-time type normalization — the generic coercion registry.

Provides:
    UnsafeCoercion  — raised when a coercion is unregistered or fails at runtime.
    normalize()     — coerce ``value`` from ``from_type`` to ``to_type``.
    register_coercer() — add or override a coercion for a (from, to) pair.

The registry is open: a consuming project can register coercers for its own
data types without forking the core. Coercers must raise ``UnsafeCoercion``
(not a bare exception) when a value cannot be safely converted, so the engine
can route it to human review instead of crashing the ingest.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from zipper.types import ZipperingDataType


class UnsafeCoercion(Exception):  # noqa: N818 — mirrors the original TS name
    """Raised when a type coercion is either unregistered or fails at runtime."""

    def __init__(
        self,
        from_type: str,
        to_type: str,
        value: Any,
        detail: str | None = None,
    ) -> None:
        msg = f"Unsafe coercion {from_type}->{to_type} for value {value!r}"
        if detail:
            msg = f"{msg}: {detail}"
        super().__init__(msg)
        self.from_type = from_type
        self.to_type = to_type
        self.value = value
        self.detail = detail


_CoercionKey = str  # "{from}->{to}"
_Coercer = Callable[[Any], Any]


def _text_to_integer(v: Any) -> int:
    if not isinstance(v, str):
        raise UnsafeCoercion("text", "integer", v)
    try:
        return int(v, 10)
    except ValueError:
        raise UnsafeCoercion("text", "integer", v) from None


def _text_to_numeric(v: Any) -> float:
    if not isinstance(v, (str, int, float)):
        raise UnsafeCoercion("text", "numeric", v)
    try:
        f = float(v)
    except (ValueError, TypeError):
        raise UnsafeCoercion("text", "numeric", v) from None
    # Reject nan/inf: they don't round-trip through standard JSON and would
    # corrupt the JSON-encoded value columns / break downstream consumers.
    if not math.isfinite(f):
        raise UnsafeCoercion("text", "numeric", v, "non-finite (nan/inf) not allowed")
    return f


def _integer_to_timestamp(v: Any) -> str:
    return (
        datetime.fromtimestamp(int(v) / 1000.0, tz=UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _timestamp_to_integer(v: Any) -> int:
    dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    return int(dt.timestamp() * 1000)


def _text_to_timestamp(v: Any) -> str:
    try:
        s = str(v)
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    except (ValueError, TypeError):
        raise UnsafeCoercion("text", "timestamp", v) from None


def _text_to_boolean(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        lowered = v.strip().lower()
        if lowered in ("true", "t", "1", "yes", "y"):
            return True
        if lowered in ("false", "f", "0", "no", "n"):
            return False
    raise UnsafeCoercion("text", "boolean", v)


_REGISTRY: dict[_CoercionKey, _Coercer] = {
    "integer->text": lambda v: str(v),
    "numeric->text": lambda v: str(v),
    "boolean->text": lambda v: "true" if v else "false",
    "text->integer": _text_to_integer,
    "text->numeric": _text_to_numeric,
    "text->boolean": _text_to_boolean,
    "integer->numeric": lambda v: float(v),
    "integer->timestamp": _integer_to_timestamp,
    "timestamp->integer": _timestamp_to_integer,
    "text->timestamp": _text_to_timestamp,
    "text->string[]": lambda v: [v],
    "string[]->jsonb": lambda v: v,
    "text->jsonb": lambda v: v,
}


def register_coercer(
    from_type: str,
    to_type: str,
    coercer: _Coercer,
) -> None:
    """
    Register (or override) a coercion for a (from_type, to_type) pair.

    Lets a consuming project extend the type system without forking core.
    The coercer should raise ``UnsafeCoercion`` on values it cannot convert.
    """
    _REGISTRY[f"{from_type}->{to_type}"] = coercer


def normalize(
    value: Any,
    from_type: ZipperingDataType | str,
    to_type: ZipperingDataType | str,
) -> Any:
    """
    Coerce ``value`` from ``from_type`` to ``to_type``.

    - Identity (from == to): returned unchanged.
    - Registered coercion: applied; may raise ``UnsafeCoercion``.
    - Unregistered pair: raises ``UnsafeCoercion``.
    """
    if from_type == to_type:
        return value

    coercer = _REGISTRY.get(f"{from_type}->{to_type}")
    if coercer is None:
        raise UnsafeCoercion(from_type, to_type, value)
    return coercer(value)
