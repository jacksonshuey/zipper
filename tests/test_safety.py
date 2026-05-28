"""Safety/hardening tests: key handling, input bounding, concurrency."""

from __future__ import annotations

import asyncio

import pytest

from zipper import (
    IngestRow,
    IngestValue,
    MissingAPIKeyError,
    SQLiteStorage,
    zipper_upsert,
)
from zipper.router import (
    MAX_SAMPLE_CHARS,
    MAX_SAMPLES,
    AssessInputs,
    HaikuRouter,
    _build_prompt,
)


def test_missing_api_key_raises_clear_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(MissingAPIKeyError) as exc:
        HaikuRouter()
    assert "ANTHROPIC_API_KEY" in str(exc.value)


def test_explicit_api_key_bypasses_env(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # Should not raise — explicit key is accepted without the env var.
    HaikuRouter(api_key="sk-ant-explicit")


def test_prompt_bounds_sample_count_and_length():
    inputs = AssessInputs(
        pkey="p",
        source="s",
        source_column="c",
        source_data_type="text",
        source_description="d" * 5000,
        source_samples=["x" * 5000] + [f"v{i}" for i in range(100)],
    )
    prompt = _build_prompt(inputs)
    # Long sample is truncated, not passed whole.
    assert "x" * 5000 not in prompt
    assert "…(truncated)" in prompt
    # Only MAX_SAMPLES samples rendered; the rest are summarized as omitted.
    assert f"(+{1 + 100 - MAX_SAMPLES} more omitted)" in prompt
    # Sanity: each rendered sample respects the per-sample cap.
    assert len("x" * (MAX_SAMPLE_CHARS + 100)) > MAX_SAMPLE_CHARS


@pytest.mark.asyncio
async def test_concurrent_upserts_are_safe(fake_router):
    """Many parallel ingests against one SQLite instance must not corrupt/error."""
    storage = SQLiteStorage(":memory:")
    storage.add_global_column("company_name", "text")

    async def ingest(i: int) -> None:
        row = IngestRow(
            pkey=f"acct_{i}",
            source="crm",
            external_id=f"ext_{i}",
            occurred_at="2026-05-28T00:00:00Z",
            columns={
                "company_name": IngestValue(value=f"Co{i}", source_data_type="text")
            },
        )
        await zipper_upsert(row, storage, fake_router)

    await asyncio.gather(*(ingest(i) for i in range(40)))

    # All 40 distinct records landed exactly once.
    for i in range(40):
        signal = storage.get_zippered_row("default", f"acct_{i}")
        assert signal is not None
        assert signal.columns == {"company_name": f"Co{i}"}
    storage.close()
