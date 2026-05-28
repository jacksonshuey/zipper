"""Rate-limit tests use a fake clock and reset state — no network, no sleeps."""

from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from tests.conftest import FakeRouter  # noqa: E402
from zipper import api, ratelimit  # noqa: E402

TOKEN = "rl-token"
OTHER = "rl-token-2"
PATH = "/v1/signals/default/missing"  # authorized → 404, so non-429 means "allowed"


@pytest.fixture
def clock(monkeypatch):
    """A controllable monotonic clock for ratelimit._now."""
    state = {"t": 1000.0}
    monkeypatch.setattr(ratelimit, "_now", lambda: state["t"])
    return state


@pytest.fixture
def client(monkeypatch, clock):
    monkeypatch.setenv("ZIPPER_API_KEYS", f"{TOKEN},{OTHER}")
    monkeypatch.delenv("ZIPPER_ALLOW_NO_AUTH", raising=False)
    monkeypatch.setenv("ZIPPER_RATE_LIMIT", "3")
    monkeypatch.setenv("ZIPPER_RATE_WINDOW_S", "60")
    monkeypatch.setattr(api, "_router", FakeRouter())
    ratelimit.reset()
    return TestClient(api.app, headers={"Authorization": f"Bearer {TOKEN}"})


def test_allows_up_to_limit_then_429(client):
    for _ in range(3):
        assert client.get(PATH).status_code == 404
    blocked = client.get(PATH)
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1


def test_window_slides_and_recovers(client, clock):
    for _ in range(3):
        assert client.get(PATH).status_code == 404
    assert client.get(PATH).status_code == 429
    # Advance past the window; the bucket clears and requests are allowed again.
    clock["t"] += 61
    assert client.get(PATH).status_code == 404


def test_limit_is_per_token(client):
    for _ in range(3):
        assert client.get(PATH).status_code == 404
    assert client.get(PATH).status_code == 429
    # A different token has its own bucket and is unaffected.
    resp = client.get(PATH, headers={"Authorization": f"Bearer {OTHER}"})
    assert resp.status_code == 404


def test_unset_limit_means_unlimited(monkeypatch, clock):
    monkeypatch.setenv("ZIPPER_API_KEYS", TOKEN)
    monkeypatch.delenv("ZIPPER_RATE_LIMIT", raising=False)
    monkeypatch.setattr(api, "_router", FakeRouter())
    ratelimit.reset()
    c = TestClient(api.app, headers={"Authorization": f"Bearer {TOKEN}"})
    for _ in range(25):
        assert c.get(PATH).status_code == 404
