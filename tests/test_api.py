"""API tests patch the module-level router with a fake — no network calls."""

from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from tests.conftest import FakeRouter  # noqa: E402
from zipper import api  # noqa: E402

TOKEN = "test-token-123"


@pytest.fixture
def client(monkeypatch):
    """An authenticated client: one configured key, header sent by default."""
    monkeypatch.setenv("ZIPPER_API_KEYS", TOKEN)
    monkeypatch.delenv("ZIPPER_ALLOW_NO_AUTH", raising=False)
    monkeypatch.setattr(api, "_router", FakeRouter())
    api._storage.add_global_column("company_name", "text")
    return TestClient(api.app, headers={"Authorization": f"Bearer {TOKEN}"})


def test_health_needs_no_auth(monkeypatch):
    # No keys configured and no opt-out: /v1 would 503, but /health stays open.
    monkeypatch.delenv("ZIPPER_API_KEYS", raising=False)
    monkeypatch.delenv("ZIPPER_ALLOW_NO_AUTH", raising=False)
    assert TestClient(api.app).get("/health").json() == {"status": "ok"}


def test_ingest_and_fetch(client):
    payload = {
        "pkey": "acct_api",
        "source": "crm",
        "external_id": "api_1",
        "occurred_at": "2026-05-28T00:00:00Z",
        "columns": {
            "Company Name": {"value": "Acme", "source_data_type": "text"},
        },
    }
    resp = client.post("/v1/ingest", json=payload)
    assert resp.status_code == 200
    assert resp.json()["decisions"][0]["canonical_name"] == "company_name"

    signal = client.get("/v1/signals/default/acct_api")
    assert signal.status_code == 200
    assert signal.json()["columns"] == {"company_name": "Acme"}


def test_signal_404_when_missing(client):
    assert client.get("/v1/signals/default/does_not_exist").status_code == 404


def test_missing_token_is_rejected(client):
    # Same configured key, but no Authorization header on this request.
    resp = client.get("/v1/signals/default/acct_api", headers={"Authorization": ""})
    assert resp.status_code == 401
    assert resp.headers.get("WWW-Authenticate") == "Bearer"


def test_wrong_token_is_rejected(client):
    resp = client.get(
        "/v1/signals/default/acct_api",
        headers={"Authorization": "Bearer not-the-token"},
    )
    assert resp.status_code == 401


def test_malformed_scheme_is_rejected(client):
    resp = client.get(
        "/v1/signals/default/acct_api",
        headers={"Authorization": f"Basic {TOKEN}"},
    )
    assert resp.status_code == 401


def test_unconfigured_auth_returns_503(monkeypatch):
    monkeypatch.delenv("ZIPPER_API_KEYS", raising=False)
    monkeypatch.delenv("ZIPPER_ALLOW_NO_AUTH", raising=False)
    monkeypatch.setattr(api, "_router", FakeRouter())
    resp = TestClient(api.app).get("/v1/signals/default/whatever")
    assert resp.status_code == 503


def test_allow_no_auth_opt_out(monkeypatch):
    monkeypatch.delenv("ZIPPER_API_KEYS", raising=False)
    monkeypatch.setenv("ZIPPER_ALLOW_NO_AUTH", "1")
    monkeypatch.setattr(api, "_router", FakeRouter())
    # Open mode: a missing pkey reaches the handler and 404s rather than 401/503.
    resp = TestClient(api.app).get("/v1/signals/default/whatever")
    assert resp.status_code == 404


def test_multiple_keys_each_accepted(monkeypatch):
    monkeypatch.setenv("ZIPPER_API_KEYS", "key-a, key-b ,key-c")
    monkeypatch.setattr(api, "_router", FakeRouter())
    for key in ("key-a", "key-b", "key-c"):
        resp = TestClient(api.app).get(
            "/v1/signals/default/missing",
            headers={"Authorization": f"Bearer {key}"},
        )
        # Authorized (reaches handler) → 404 for the missing pkey, not 401.
        assert resp.status_code == 404
