"""Boundary validation on IngestRow inputs."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from zipper import IngestRow, IngestValue


def _cols() -> dict[str, IngestValue]:
    return {"c": IngestValue(value="1", source_data_type="text")}


def test_empty_pkey_rejected():
    with pytest.raises(ValidationError):
        IngestRow(pkey="", source="s", occurred_at="2026-01-01T00:00:00Z", columns=_cols())


def test_empty_source_rejected():
    with pytest.raises(ValidationError):
        IngestRow(pkey="p", source="", occurred_at="2026-01-01T00:00:00Z", columns=_cols())


def test_empty_occurred_at_rejected():
    with pytest.raises(ValidationError):
        IngestRow(pkey="p", source="s", occurred_at="", columns=_cols())


def test_non_iso_occurred_at_rejected():
    with pytest.raises(ValidationError):
        IngestRow(pkey="p", source="s", occurred_at="totally not a date", columns=_cols())


def test_iso_occurred_at_with_z_accepted():
    row = IngestRow(pkey="p", source="s", occurred_at="2026-05-28T00:00:00Z", columns=_cols())
    assert row.occurred_at == "2026-05-28T00:00:00Z"


def test_custom_data_type_accepted():
    # Data-type fields are str, not a closed Literal: a consuming project can
    # register its own coercers and declare domain types (e.g. a healthcare
    # port adding "quantity_with_unit") without forking the core models.
    val = IngestValue(value=1, source_data_type="quantity_with_unit")
    assert val.source_data_type == "quantity_with_unit"


def test_valid_row_accepted():
    row = IngestRow(pkey="p", source="s", occurred_at="2026-01-01T00:00:00Z", columns=_cols())
    assert row.workspace_key == "default"
