import pytest

from zipper import (
    IngestRow,
    IngestValue,
    MemoryStorage,
    SQLiteStorage,
    get_decision_history,
    get_merged_record,
    zipper_upsert,
)
from zipper.lookup import LookupVerdict
from zipper.router import AssessInputs
from zipper.types import RoutingVerdict

pytestmark = pytest.mark.asyncio


def _const_router(canonical_name: str):
    """A router that maps every column to one fixed canonical name."""

    class _R:
        def __init__(self) -> None:
            self.calls: list = []

        async def assess(self, inputs: AssessInputs) -> RoutingVerdict:
            self.calls.append(inputs)
            return RoutingVerdict(
                verdict="append",
                canonical_name=canonical_name,
                is_global_target=False,
                similarity_score=0.3,
                reason="const",
            )

    return _R()


async def test_canonical_collision_flags_review():
    storage = MemoryStorage()
    router = _const_router("company")  # both columns -> "company"
    row = IngestRow(
        pkey="acct_1",
        source="crm",
        external_id="e",
        occurred_at="2026-05-28T00:00:00Z",
        columns={
            "Company": IngestValue(value="A", source_data_type="text"),
            "Org": IngestValue(value="B", source_data_type="text"),
        },
    )
    result = await zipper_upsert(row, storage, router)
    collisions = [d for d in result.decisions if d.decided_by == "collision"]
    assert len(collisions) == 1 and collisions[0].needs_review
    signal = storage.get_zippered_row("default", "acct_1")
    assert signal is not None
    assert signal.columns == {"company": "B"}  # last value wins, single key


async def test_get_merged_record_across_sources(fake_router):
    storage = MemoryStorage()
    storage.add_global_column("company_name", "text")
    storage.add_global_column("employee_count", "integer")

    await zipper_upsert(
        IngestRow(
            pkey="acct_1", source="crm", external_id="a",
            occurred_at="2026-05-28T00:00:00Z",
            columns={"company_name": IngestValue(value="Acme", source_data_type="text")},
        ),
        storage, fake_router,
    )
    await zipper_upsert(
        IngestRow(
            pkey="acct_1", source="hr", external_id="b",
            occurred_at="2026-05-28T01:00:00Z",
            columns={"employee_count": IngestValue(value="240", source_data_type="text")},
        ),
        storage, fake_router,
    )

    merged = await get_merged_record("default", "acct_1", storage)
    assert merged == {"company_name": "Acme", "employee_count": 240}


def _row(**cols) -> IngestRow:
    return IngestRow(
        pkey="acct_1",
        source="crm_export",
        external_id="ext_1",
        occurred_at="2026-05-28T00:00:00Z",
        columns={k: IngestValue(**v) for k, v in cols.items()},
    )


async def test_append_then_reconcile(fake_router):
    storage = MemoryStorage()
    storage.add_global_column("company_name", "text")
    storage.add_global_column("employee_count", "integer")

    row = _row(
        company_name={"value": "Acme", "source_data_type": "text"},
        employee_count={"value": "240", "source_data_type": "text"},
    )
    result = await zipper_upsert(row, storage, fake_router)

    signal = storage.get_zippered_row("default", "acct_1")
    assert signal is not None
    assert signal.columns == {"company_name": "Acme", "employee_count": 240}
    assert all(d.decided_by == "llm" for d in result.decisions)


async def test_decision_is_cached(fake_router):
    storage = MemoryStorage()
    storage.add_global_column("company_name", "text")

    row = _row(company_name={"value": "Acme", "source_data_type": "text"})
    await zipper_upsert(row, storage, fake_router)
    calls_after_first = len(fake_router.calls)

    await zipper_upsert(row, storage, fake_router)
    # Cache hit on second ingest — no new router call.
    assert len(fake_router.calls) == calls_after_first


async def test_unsafe_coercion_flags_review(fake_router):
    storage = MemoryStorage()
    storage.add_global_column("employee_count", "integer")

    row = _row(employee_count={"value": "not-a-number", "source_data_type": "text"})
    result = await zipper_upsert(row, storage, fake_router)

    review = [d for d in result.decisions if d.decided_by == "normalizer"]
    assert len(review) == 1
    assert review[0].needs_review is True

    signal = storage.get_zippered_row("default", "acct_1")
    assert signal is not None
    # Value was skipped, not crashed.
    assert "employee_count" not in signal.columns


async def test_lookup_tier_short_circuits_router(fake_router):
    class StaticLookup:
        def match(self, source_column, samples):
            if source_column == "loinc_code":
                return LookupVerdict(
                    canonical_column="hemoglobin",
                    data_type="text",
                    matched_on="column_name",
                    reason="exact code column",
                )
            return None

    storage = MemoryStorage()
    row = _row(loinc_code={"value": "718-7", "source_data_type": "text"})
    result = await zipper_upsert(row, storage, fake_router, lookup=StaticLookup())

    assert fake_router.calls == []  # router never consulted
    assert result.decisions[0].decided_by == "lookup"
    assert result.decisions[0].canonical_name == "hemoglobin"


async def test_unclear_marks_needs_review():
    def decide(inputs: AssessInputs) -> RoutingVerdict:
        return RoutingVerdict(
            verdict="unclear",
            canonical_name="mystery_field",
            is_global_target=False,
            similarity_score=0.1,
            reason="ambiguous samples",
        )

    from tests.conftest import FakeRouter

    router = FakeRouter(decide=decide)
    storage = MemoryStorage()
    row = _row(weird={"value": "??", "source_data_type": "text"})
    result = await zipper_upsert(row, storage, router)

    assert result.decisions[0].verdict == "unclear"
    assert result.decisions[0].needs_review is True


async def test_decision_history_is_append_only(fake_router):
    storage = MemoryStorage()
    storage.add_global_column("company_name", "text")
    row = _row(company_name={"value": "Acme", "source_data_type": "text"})

    await zipper_upsert(row, storage, fake_router)
    history = await get_decision_history("default", "acct_1", "company_name", storage)
    assert len(history) >= 1


async def test_sqlite_backend_end_to_end(fake_router):
    storage = SQLiteStorage(":memory:")
    storage.add_global_column("company_name", "text")
    storage.add_global_column("employee_count", "integer")

    row = _row(
        company_name={"value": "Acme", "source_data_type": "text"},
        employee_count={"value": "240", "source_data_type": "text"},
    )
    await zipper_upsert(row, storage, fake_router)

    signal = storage.get_zippered_row("default", "acct_1")
    assert signal is not None
    assert signal.columns == {"company_name": "Acme", "employee_count": 240}
    storage.close()
