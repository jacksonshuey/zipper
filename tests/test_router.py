"""Router tests use a fake Anthropic client — no network, no API key needed."""

from __future__ import annotations

import pytest

from zipper.router import AssessInputs, HaikuRouter


class _Block:
    def __init__(self, type_, name, input_):
        self.type = type_
        self.name = name
        self.input = input_


class _Response:
    def __init__(self, content):
        self.content = content


class _FakeMessages:
    def __init__(self, tool_input):
        self._tool_input = tool_input

    async def create(self, **kwargs):
        return _Response(
            [_Block("tool_use", "zippering_routing_verdict", self._tool_input)]
        )


class _FakeClient:
    def __init__(self, tool_input):
        self.messages = _FakeMessages(tool_input)


def _inputs() -> AssessInputs:
    return AssessInputs(
        pkey="acct_1",
        source="crm",
        source_column="Company",
        source_data_type="text",
        source_description=None,
        source_samples=["Acme"],
    )


@pytest.mark.asyncio
async def test_router_parses_valid_verdict():
    client = _FakeClient(
        {
            "verdict": "join",
            "canonical_name": "company_name",
            "is_global_target": True,
            "similarity_score": 0.97,
            "reason": "same field",
        }
    )
    router = HaikuRouter(client=client)
    verdict = await router.assess(_inputs())
    assert verdict.verdict == "join"
    assert verdict.canonical_name == "company_name"
    assert verdict.is_global_target is True


@pytest.mark.asyncio
async def test_router_rejects_bad_verdict():
    client = _FakeClient(
        {
            "verdict": "nonsense",
            "canonical_name": "x",
            "is_global_target": False,
            "similarity_score": 0.5,
            "reason": "r",
        }
    )
    router = HaikuRouter(client=client)
    with pytest.raises(RuntimeError):
        await router.assess(_inputs())


@pytest.mark.asyncio
async def test_router_rejects_out_of_range_score():
    client = _FakeClient(
        {
            "verdict": "append",
            "canonical_name": "x",
            "is_global_target": False,
            "similarity_score": 1.5,
            "reason": "r",
        }
    )
    router = HaikuRouter(client=client)
    with pytest.raises(RuntimeError):
        await router.assess(_inputs())
