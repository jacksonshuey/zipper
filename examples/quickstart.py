"""
Runnable quickstart. Requires ANTHROPIC_API_KEY in the environment.

    python examples/quickstart.py
"""

import asyncio

from zippering import HaikuRouter, IngestRow, IngestValue, MemoryStorage, zipper_upsert


async def main() -> None:
    storage = MemoryStorage()
    storage.add_global_column("company_name", "text", "Display name of the account")
    storage.add_global_column("employee_count", "integer", "Approximate headcount")

    router = HaikuRouter()

    # Two sources describe the same account with different column names/shapes.
    rows = [
        IngestRow(
            pkey="acct_123",
            source="crm_export",
            external_id="crm_1",
            occurred_at="2026-05-28T00:00:00Z",
            columns={
                "Company": IngestValue(value="Acme Inc", source_data_type="text"),
                "Headcount": IngestValue(value="240", source_data_type="text"),
            },
        ),
        IngestRow(
            pkey="acct_123",
            source="vendor_csv",
            external_id="vc_1",
            occurred_at="2026-05-28T01:00:00Z",
            columns={
                "company_nm": IngestValue(value="Acme Inc", source_data_type="text"),
                "num_staff": IngestValue(value="245", source_data_type="text"),
            },
        ),
    ]

    for row in rows:
        result = await zipper_upsert(row, storage, router)
        print(f"\n{row.source}:")
        for d in result.decisions:
            print(f"  {d.source_column:>12}  ->  {d.canonical_name:<16} ({d.verdict})")

    signal = await storage.get_zippered_row("default", "acct_123")
    assert signal is not None
    print("\nReconciled record:", signal.columns)


if __name__ == "__main__":
    asyncio.run(main())
