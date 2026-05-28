"""API tests patch the module-level router with a fake — no network calls."""

from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from tests.conftest import FakeRouter  # noqa: E402
from zippering import api  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(api, "_router", FakeRouter())
    api._storage.add_global_column("company_name", "text")
    return TestClient(api.app)


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


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
