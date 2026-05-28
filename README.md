# Zipper

**A universal, LLM-assisted schema-reconciliation engine.** Point it at any
source — a CRM export, a vendor CSV, a JSON API, a webhook payload — and for
every incoming column it decides whether to **JOIN** an existing canonical
column, **APPEND** a new one, or flag it **UNCLEAR** for review. It normalizes
each value to the canonical type and writes a wide reconciled row plus an
append-only audit of every routing decision.

It's the "zipper" because it merges many differently-shaped sources into one
coherent canonical schema, one column at a time.

```
heterogeneous source rows ──┐
   crm_export: "Company"     │
   vendor_csv: "company_nm"  ├──►  Zippering  ──►  canonical record
   api: "organization"       │     (cache → lookup → LLM)     { company_name: ... }
                             ─┘     + append-only decision log
```

## Why

Every integration project re-solves the same problem: incoming fields never
line up with your canonical model, and gluing them together by hand doesn't
scale. Zippering makes that routing decision once per `(record, source,
column)`, caches it, and records *why* — so the next row with the same shape is
free and every decision is auditable.

## Install

Install straight from the repo (the package name on PyPI is taken, so zipper
is distributed from GitHub):

```bash
# library
pip install "git+https://github.com/jacksonshuey/zipper.git"

# + the FastAPI HTTP service
pip install "zipper[api] @ git+https://github.com/jacksonshuey/zipper.git"
```

Or from a local clone:

```bash
pip install .          # library
pip install ".[api]"   # + HTTP service
```

Requires Python 3.11+. Pin a release with `...zipper.git@v0.1.0`.

## Anthropic API key

Zipper never hardcodes or stores a key. You supply it one of two ways:

```python
# 1. Pass it as a field (explicit, per-router):
router = HaikuRouter(api_key="sk-ant-...")

# 2. Or omit it and let the Anthropic SDK read ANTHROPIC_API_KEY from the env:
router = HaikuRouter()
```

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # used when no api_key field is passed
```

## Quickstart

```python
import asyncio
from zipper import IngestRow, IngestValue, MemoryStorage, HaikuRouter, zipper_upsert

async def main():
    storage = MemoryStorage()
    storage.add_global_column("company_name", "text", "Display name of the account")
    storage.add_global_column("employee_count", "integer", "Headcount")
    router = HaikuRouter()  # uses ANTHROPIC_API_KEY

    row = IngestRow(
        pkey="acct_123",
        source="crm_export",
        external_id="crm_123",
        occurred_at="2026-05-28T00:00:00Z",
        columns={
            "Company":   IngestValue(value="Acme Inc", source_data_type="text"),
            "Headcount": IngestValue(value="240",      source_data_type="text"),
        },
    )

    result = await zipper_upsert(row, storage, router)
    for d in result.decisions:
        print(d.source_column, "->", d.canonical_name, f"({d.verdict})")

    signal = await storage.get_zippered_row("default", "acct_123")
    print(signal.columns)   # {'company_name': 'Acme Inc', 'employee_count': 240}

asyncio.run(main())
```

## Reading reconciled data

Signals are stored per `(source, external_id)`, so one record can have several
rows (one per source occurrence). Two ways to read:

```python
from zipper import get_zippered_row, get_merged_record

# The single latest signal row (one source's columns):
latest = await get_zippered_row("default", "acct_123", storage)

# All sources collapsed into one wide record, newest-wins per column:
record = await get_merged_record("default", "acct_123", storage)
```

When two columns in the *same* row route to the same canonical name, the last
value wins and a `needs_review` decision (`decided_by="collision"`) is recorded
so the overwrite is auditable.

## The three routing tiers

For each incoming column, in order:

1. **Cache** — if a decision already exists for `(pkey, source, source_column)`,
   reuse it. No LLM call. Routing is decided once and stays stable.
2. **Lookup** *(optional)* — a deterministic, rule-based matcher you inject.
   The core ships the `Lookup` Protocol but **no** registries; bring your own
   (codes, regexes, exact-name maps) for the matches you never want an LLM to
   second-guess.
3. **Router** — an LLM (`HaikuRouter`, backed by Anthropic) decides JOIN /
   APPEND / UNCLEAR using a forced tool-call with a strict schema.

## Everything is pluggable

| Seam        | Protocol  | Ships                                  | Bring your own |
|-------------|-----------|----------------------------------------|----------------|
| Persistence | `Storage` | `MemoryStorage`, `SQLiteStorage`       | Postgres, Snowflake, … |
| Routing     | `Router`  | `HaikuRouter` (Anthropic, key from env)| any LLM/provider |
| Tier-1      | `Lookup`  | Protocol only                          | your registries |
| Types       | —         | 7 universal types + coercion registry  | `register_coercer()` |

Add a data type without forking core:

```python
from zipper import register_coercer, UnsafeCoercion

def to_cents(v):
    try:
        return round(float(v) * 100)
    except (TypeError, ValueError):
        raise UnsafeCoercion("text", "cents", v)

register_coercer("text", "cents", to_cents)
```

Swap in persistent SQLite:

```python
from zipper import SQLiteStorage
storage = SQLiteStorage("./zipper.db")   # schema applied automatically
```

## HTTP API

```bash
pip install "zipper[api]"
export ZIPPER_API_KEYS="client-one-token,client-two-token"   # bearer tokens
uvicorn zipper.api:app --reload
```

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET`  | `/health` | none | Liveness probe |
| `POST` | `/v1/ingest` | bearer | Ingest one `IngestRow` |
| `GET`  | `/v1/signals/{workspace_key}/{pkey}` | bearer | Latest reconciled row |
| `GET`  | `/v1/timeline/{workspace_key}/{pkey}?since=ISO` | bearer | Rows since a timestamp |
| `GET`  | `/v1/decisions/{workspace_key}/{pkey}/{canonical_name}` | bearer | Decision audit |

### Authentication

The `/v1/*` routes require a bearer token. Configure accepted client tokens via
`ZIPPER_API_KEYS` (comma-separated), then send `Authorization: Bearer <token>`:

```bash
curl -H "Authorization: Bearer client-one-token" \
  http://localhost:8000/v1/signals/default/acct_123
```

Auth is **secure by default**: if `ZIPPER_API_KEYS` is unset, the protected
routes return `503` rather than serving open. To intentionally run without auth
(e.g. behind your own gateway), set `ZIPPER_ALLOW_NO_AUTH=1`. Tokens are
compared in constant time and never logged or persisted. This is coarse,
service-level auth — pair it with TLS and a rate limit before exposing the API
publicly.

## Invariants

- **`zippering_decisions` is append-only.** Overrides and normalizer flags
  insert *new* rows; nothing is updated in place. The latest row by
  `decided_at` is the active routing.
- **Routing is cached per `(pkey, source, source_column)`** — stable and cheap.
- **Unsafe coercions never crash ingest** — they append a `needs_review`
  decision and skip the value.

## Security

zipper is BYO-key (never stored or logged), bounds untrusted source data before
it reaches the model, uses parameterized SQL, and ships thread-safe storage. The
bundled HTTP API has no built-in auth — gate it yourself before exposing it. See
[SECURITY.md](SECURITY.md) for the full model.

## Origin

Zippering started as a TypeScript engine inside Dugout and a Python port inside
EHRzipper (a healthcare data product). This package is the generic core, with
all domain-specific extensions removed, so it drops into any project.

## License

MIT
