"""Contract test: `SessionKeyProvider`'s job-scoped fetch vs. service-sessions' published
OpenAPI contract for `GET /internal/jobs/{job_id}/session-key` (#94 follow-up).

Both the pre-#94 and post-#94 unit tests in ``test_key_provider.py`` only ever assert what
*this* client believes the wire contract is (first a query param, now a header) — never what
the server actually requires, so neither generation would have caught #94's bug (every call
got a guaranteed 422). This test instead pins the parameter contract straight from
service-sessions' own committed, drift-guarded spec (that repo's
``tests/integration/test_openapi_contract_parity.py`` fails its build if the spec and the
generated schema disagree), and asserts the request this client actually sends satisfies it.

Pinned from ``bechtleav360/avs.ai.idac.service-sessions`` @ ``d5ee98f0dd29679ca52db753d2481858ae5cc509``,
``docs/openapi.yaml``, path ``/internal/jobs/{job_id}/session-key``. Refresh ``_PINNED_CONTRACT``
(and the commit SHA above) if that route's contract changes upstream.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
import respx
from cachetools import TTLCache

from blueprint.agents.services.sessions.key_provider import SessionKeyProvider

# Transcribed by hand rather than parsed from a checked-out copy of the YAML — this repo
# has no dependency on service-sessions' sources or docs, and a hand-pin makes the "refresh
# this if the upstream contract changes" note above actually actionable (there is nothing to
# re-fetch automatically).
_PINNED_CONTRACT: dict[str, Any] = {
    "operationId": "getJobSessionKey",
    "parameters": [
        {"name": "X-Agent-Id", "in": "header", "required": True, "schema": {"type": "string"}},
        {"name": "X-Api-Key", "in": "header", "required": True, "schema": {"type": "string"}},
    ],
}

_JOB_REMOTE_URL = "http://sessions.local:8001"


def _required_headers(contract: dict[str, Any]) -> set[str]:
    return {p["name"] for p in contract["parameters"] if p["in"] == "header" and p["required"]}


def _make_job_provider() -> SessionKeyProvider:
    provider = SessionKeyProvider()
    provider._source = "job"
    provider._remote_url = _JOB_REMOTE_URL
    provider._api_key = "sekrit"
    provider._agent_id = "agent-42"
    provider._cache = TTLCache(maxsize=100, ttl=60)
    return provider


class TestSessionKeyJobFetchMatchesPublishedContract:
    def test_pinned_contract_declares_no_query_parameters(self) -> None:
        """Sanity-check the pin itself: the published contract has zero query params.

        If this ever fails, the upstream contract changed shape (e.g. `agent_id` moved back
        to the query string) and `_PINNED_CONTRACT` needs a matching update before the
        request-shape assertion below means anything.
        """
        assert all(p["in"] != "query" for p in _PINNED_CONTRACT["parameters"])

    @respx.mock
    async def test_request_satisfies_pinned_contract(self) -> None:
        job_id = uuid4()
        route = respx.get(f"{_JOB_REMOTE_URL}/internal/jobs/{job_id}/session-key").mock(
            return_value=httpx.Response(200, json={"session_key": "job-secret"})
        )
        provider = _make_job_provider()

        await provider.get_session_key(uuid4(), job_id=job_id)

        request = route.calls.last.request
        for header_name in _required_headers(_PINNED_CONTRACT):
            assert header_name in request.headers, f"contract requires {header_name!r} header, request has none"
        # The contract declares zero query parameters (checked above) — any query string on
        # the actual request is drift, not just the historical `?agent_id=...` shape #94 hit.
        assert not dict(request.url.params), f"contract declares no query params, request sent: {dict(request.url.params)}"
