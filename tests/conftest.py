"""Shared test fixtures: a deterministic fake router (no network calls)."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from zippering.router import AssessInputs
from zippering.types import RoutingVerdict


class FakeRouter:
    """
    A Router that returns a scripted verdict. Defaults to a sensible
    name-normalizing JOIN/APPEND so tests don't hit the network.
    """

    def __init__(
        self,
        decide: Callable[[AssessInputs], RoutingVerdict] | None = None,
    ) -> None:
        self._decide = decide or self._default
        self.calls: list[AssessInputs] = []

    @staticmethod
    def _default(inputs: AssessInputs) -> RoutingVerdict:
        # Snake-case the column name; JOIN a global if the name matches one.
        canonical = inputs.source_column.strip().lower().replace(" ", "_")
        global_match = next(
            (g for g in inputs.candidates_global if g.name == canonical), None
        )
        return RoutingVerdict(
            verdict="join" if global_match else "append",
            canonical_name=canonical,
            is_global_target=global_match is not None,
            similarity_score=0.95 if global_match else 0.4,
            reason="fake router decision",
        )

    async def assess(self, inputs: AssessInputs) -> RoutingVerdict:
        self.calls.append(inputs)
        return self._decide(inputs)


@pytest.fixture
def fake_router() -> FakeRouter:
    return FakeRouter()
