"""
LLM column-routing assessor.

Wraps a single Anthropic call (temperature 0, forced tool_choice) that decides
whether an incoming integration column should:
  - JOIN an existing canonical column (global or per-pkey)
  - APPEND as a new canonical column
  - UNCLEAR: ambiguous samples — flag for human review

The Anthropic integration is intentionally kept constant across all consuming
projects: same model id, same forced tool_choice, same strict input_schema,
same timeout, and the API key resolved from ``ANTHROPIC_API_KEY`` via the
SDK's default client. Inject a fake client in tests.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from typing import Any, Protocol, cast, runtime_checkable

import anthropic

from zipper.config import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT_MS,
)
from zipper.types import (
    GlobalCanonicalColumn,
    RoutingVerdict,
    ZipperingDataType,
    ZipperingSchemaRow,
)

# Defensive bounds on untrusted source data folded into the prompt. A malicious
# or malformed source can't blow up the request past these caps.
MAX_SAMPLES = 10
MAX_SAMPLE_CHARS = 500
MAX_DESCRIPTION_CHARS = 1_000


class MissingAPIKeyError(RuntimeError):
    """Raised when no Anthropic API key can be resolved for HaikuRouter."""

# ---------------------------------------------------------------------------
# Tool schema (forced via tool_choice — guarantees structured output)
# ---------------------------------------------------------------------------

_ROUTING_TOOL: dict[str, Any] = {
    "name": "zippering_routing_verdict",
    "description": (
        "Decide how an incoming column from a source integration should route "
        "into the canonical schema for a record."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": ["join", "append", "unclear"]},
            "canonical_name": {"type": "string", "minLength": 1},
            "is_global_target": {"type": "boolean"},
            "similarity_score": {"type": "number", "minimum": 0, "maximum": 1},
            "reason": {"type": "string", "minLength": 1, "maxLength": 200},
        },
        "required": [
            "verdict",
            "canonical_name",
            "is_global_target",
            "similarity_score",
            "reason",
        ],
    },
}


@dataclass
class AssessInputs:
    """All signal data the router needs: column metadata + both candidate tiers."""

    pkey: str
    source: str
    source_column: str
    source_data_type: ZipperingDataType
    source_description: str | None
    source_samples: list[Any]
    candidates_global: list[GlobalCanonicalColumn] = field(default_factory=list)
    candidates_pkey: list[ZipperingSchemaRow] = field(default_factory=list)


@runtime_checkable
class Router(Protocol):
    """Anything that can produce a RoutingVerdict for a column."""

    async def assess(self, inputs: AssessInputs) -> RoutingVerdict:
        ...


class HaikuRouter:
    """
    Anthropic-backed router. Construct with no arguments in production
    (API key read from ANTHROPIC_API_KEY); inject a fake client in tests.
    """

    def __init__(
        self,
        client: anthropic.AsyncAnthropic | None = None,
        model: str = DEFAULT_MODEL,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        api_key: str | None = None,
    ) -> None:
        if client is not None:
            self._client = client
        elif api_key is not None:
            self._client = anthropic.AsyncAnthropic(api_key=api_key)
        elif os.environ.get("ANTHROPIC_API_KEY"):
            self._client = anthropic.AsyncAnthropic()
        else:
            raise MissingAPIKeyError(
                "No Anthropic API key found. Either pass it explicitly — "
                "HaikuRouter(api_key='sk-ant-...') — or set the ANTHROPIC_API_KEY "
                "environment variable. zipper never stores or logs the key; it is "
                "used only to construct the Anthropic client."
            )
        self._model = model
        self._timeout_ms = timeout_ms
        self._max_tokens = max_tokens

    async def assess(self, inputs: AssessInputs) -> RoutingVerdict:
        """Call the model to route a column. Raises TimeoutError on expiry."""
        return await asyncio.wait_for(
            self._call(inputs),
            timeout=self._timeout_ms / 1000.0,
        )

    async def _call(self, inputs: AssessInputs) -> RoutingVerdict:
        prompt = _build_prompt(inputs)
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=0,
            tools=cast("list[anthropic.types.ToolParam]", [_ROUTING_TOOL]),
            tool_choice=cast(
                "anthropic.types.ToolChoiceToolParam",
                {"type": "tool", "name": _ROUTING_TOOL["name"]},
            ),
            messages=[{"role": "user", "content": prompt}],
        )

        tool_use = next(
            (
                block
                for block in response.content
                if block.type == "tool_use" and block.name == _ROUTING_TOOL["name"]
            ),
            None,
        )
        if tool_use is None:
            raise RuntimeError(
                "Router returned no tool_use block for zippering_routing_verdict"
            )
        return _parse_verdict(tool_use.input)


async def assess_column_routing(
    inputs: AssessInputs,
    client: anthropic.AsyncAnthropic | None = None,
) -> RoutingVerdict:
    """Module-level convenience wrapper around HaikuRouter."""
    return await HaikuRouter(client=client).assess(inputs)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "…(truncated)"


def _build_prompt(inputs: AssessInputs) -> str:
    if inputs.source_description and inputs.source_description.strip():
        desc_line = _truncate(
            inputs.source_description.strip(), MAX_DESCRIPTION_CHARS
        )
    else:
        desc_line = "(none provided)"

    if inputs.source_samples:
        bounded = [
            _truncate(json.dumps(s), MAX_SAMPLE_CHARS)
            for s in inputs.source_samples[:MAX_SAMPLES]
        ]
        omitted = len(inputs.source_samples) - len(bounded)
        samples_line = ", ".join(bounded)
        if omitted > 0:
            samples_line += f"  (+{omitted} more omitted)"
    else:
        samples_line = "(no samples)"

    if inputs.candidates_global:
        global_section = "\n".join(
            f"  - name: {c.name}  data_type: {c.data_type}  "
            f"description: {c.description or '(no description)'}  "
            f"tags: [{', '.join(c.semantic_tags) if c.semantic_tags else '-'}]"
            for c in inputs.candidates_global
        )
    else:
        global_section = "  (none - no global canonicals exist yet)"

    if inputs.candidates_pkey:
        pkey_section = "\n".join(
            f"  - canonical_name: {c.canonical_name}  data_type: {c.data_type}  "
            f"description: {c.description or '(no description)'}"
            for c in inputs.candidates_pkey
        )
    else:
        pkey_section = "  (none - no per-record canonicals exist yet)"

    return (
        "You are deciding whether an incoming column from a data integration is "
        "semantically the same field as an existing canonical column we already "
        "track for a record.\n\n"
        "Prefer routing to a GLOBAL canonical when the match is reasonable so we "
        "can query across records later. Only route to a per-record canonical when "
        "no global is a good fit. Only APPEND a new column if neither tier matches. "
        "Return UNCLEAR when sample values are inconsistent or ambiguous - do not "
        "guess; we'll surface for human review.\n\n"
        "INCOMING COLUMN\n"
        f"  source:              {inputs.source}\n"
        f"  column_name:         {inputs.source_column}\n"
        f"  source_data_type:    {inputs.source_data_type}\n"
        f"  source_description:  {desc_line}\n"
        f"  sample_values:       {samples_line}\n\n"
        "GLOBAL CANONICAL COLUMNS (preferred match targets)\n"
        f"{global_section}\n\n"
        f"PER-RECORD CANONICAL COLUMNS (fallback match targets - pkey: {inputs.pkey})\n"
        f"{pkey_section}\n\n"
        "Rules:\n"
        '- "join" when the columns carry the same kind of data - set canonical_name '
        "to the matching global or per-record name.\n"
        '- "append" when no candidate fits - invent a snake_case name.\n'
        '- "unclear" when sample values are inconsistent or ambiguous; do not guess. '
        "Still set a canonical_name suggestion.\n"
        "- is_global_target is true only when canonical_name matches an entry in "
        "the GLOBAL candidate list.\n\n"
        "Call the zippering_routing_verdict tool with your decision."
    )


def _parse_verdict(raw: Any) -> RoutingVerdict:
    """Runtime validation of the model's tool_use input."""
    if not isinstance(raw, dict):
        raise RuntimeError(f"Router tool_use input is not an object: {json.dumps(raw)}")

    verdict = raw.get("verdict")
    if verdict not in ("join", "append", "unclear"):
        raise RuntimeError(f"Invalid verdict: {json.dumps(verdict)}")

    canonical_name = raw.get("canonical_name")
    if not isinstance(canonical_name, str) or len(canonical_name) == 0:
        raise RuntimeError(
            f"Missing or empty canonical_name: {json.dumps(canonical_name)}"
        )

    is_global_target = raw.get("is_global_target")
    if not isinstance(is_global_target, bool):
        raise RuntimeError(
            f"is_global_target must be boolean: {json.dumps(is_global_target)}"
        )

    similarity_score = raw.get("similarity_score")
    if (
        not isinstance(similarity_score, (int, float))
        or similarity_score < 0
        or similarity_score > 1
    ):
        raise RuntimeError(f"similarity_score out of range: {json.dumps(similarity_score)}")

    reason = raw.get("reason")
    if not isinstance(reason, str) or len(reason) == 0:
        raise RuntimeError(f"Missing or empty reason: {json.dumps(reason)}")

    return RoutingVerdict(
        verdict=cast("Any", verdict),
        canonical_name=canonical_name,
        is_global_target=is_global_target,
        similarity_score=float(similarity_score),
        reason=reason,
    )
