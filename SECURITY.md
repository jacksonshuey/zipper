# Security

How zipper handles secrets and untrusted data, and what to know before
exposing it to other users.

## API keys

- **Bring-your-own key.** zipper never ships, hardcodes, or commits an Anthropic
  key. You supply one of two ways:
  - `HaikuRouter(api_key="sk-ant-...")` — passed explicitly (read it from your
    own secrets manager), or
  - omit it and set the `ANTHROPIC_API_KEY` environment variable.
- The key is used only to construct the Anthropic client. It is **never logged,
  persisted, or written to storage.**
- If no key can be resolved, `HaikuRouter()` raises `MissingAPIKeyError`
  immediately with a clear message — it does not silently proceed.
- `.env` is gitignored; `.env.example` ships with empty placeholders only.

## Untrusted source data

Source column names, descriptions, and sample values are third-party data and
are folded into the LLM routing prompt. Hardening:

- **Bounded input.** Samples are capped (`MAX_SAMPLES`), and each sample plus the
  description are length-truncated (`MAX_SAMPLE_CHARS`, `MAX_DESCRIPTION_CHARS`)
  before reaching the model, so a huge or malformed value can't blow up a
  request.
- **Constrained output.** The router uses a forced `tool_choice` with a strict
  `input_schema`, and every verdict is re-validated at runtime
  (`_parse_verdict`). The model cannot return arbitrary structures.
- **Prompt-injection blast radius is small.** The worst a malicious source can do
  is influence a *routing* decision (e.g. mis-name a canonical column). It cannot
  execute code or exfiltrate data. Ambiguous cases route to `unclear` /
  `needs_review`, and the optional deterministic `Lookup` tier lets you pin the
  matches you never want an LLM to decide.

## Storage

- **Parameterized SQL only.** Every `SQLiteStorage` query uses `?` placeholders;
  no string interpolation of values. The schema loads from a bundled file.
- **Thread-safe.** `SQLiteStorage` and `MemoryStorage` serialize all public
  methods behind a lock, so concurrent `zipper_upsert` calls against one instance
  are safe.
- **In-memory by default.** `MemoryStorage` keeps nothing at rest. Durable
  backends (SQLite, or your own) are opt-in.

## Hosting the HTTP API

The bundled FastAPI app (`zipper[api]`) ships **coarse, service-level bearer
auth** and **secure-by-default** behavior:

- Set `ZIPPER_API_KEYS` (comma-separated client tokens). Requests to `/v1/*`
  must send `Authorization: Bearer <token>`; tokens are compared in constant
  time (`secrets.compare_digest`) and are never logged or persisted.
- If `ZIPPER_API_KEYS` is unset, the protected routes return `503` rather than
  serving open. To deliberately run without auth (behind your own gateway), set
  `ZIPPER_ALLOW_NO_AUTH=1`. `/health` is always public.

It has **no built-in rate limiting** and the bearer tokens are shared secrets,
not per-user identities. If you expose it publicly:

- Add a rate limit — auth alone won't stop an authorized client from driving
  Anthropic calls on your key.
- Keep the Anthropic key server-side (env/secret store); do not have clients send
  raw Anthropic keys over the wire.
- Terminate TLS so bearer tokens aren't sent in the clear.

For most use cases, prefer consuming zipper as a **library** so each user holds
their own key and no service is exposed.

## Reporting

Open a private security advisory on the repository, or email the maintainer.
Please do not file public issues for vulnerabilities.
