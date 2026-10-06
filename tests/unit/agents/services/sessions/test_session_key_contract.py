"""Contract test: `SessionKeyProvider`'s job-scoped fetch vs. service-sessions' published
OpenAPI contract for `GET /internal/jobs/{job_id}/session-key` (#94 follow-up).

Both the pre-#94 and post-#94 unit tests in ``test_key_provider.py`` only ever assert what
*this* client believes the wire contract is (first a query param, now a header) — never what
the server actually requires, so neither generation would have caught #94's bug (every call
got a guaranteed 422). This test instead pins the contract straight from service-sessions'
own committed, drift-guarded spec (that repo's ``tests/integration/test_openapi_contract_parity.py``
fails its build if the spec and the generated schema disagree), and asserts the request this
client actually sends satisfies it.

Pinned from ``bechtleav360/avs.ai.idac.service-sessions``, ``docs/openapi.yaml``, path
``/internal/jobs/{job_id}/session-key``, from two distinct parts of the spec:
``X-Agent-Id`` is a route-level ``parameters`` entry; ``X-Api-Key`` is not a
``parameters`` entry at all — it's the global `ApiKey` `securitySchemes` entry
(`type: apiKey, in: header, name: X-Api-Key`), applied via `security: [ApiKey: []]` both
globally and on this route. Refresh `_PINNED_PARAMETERS`/`_PINNED_SECURITY_HEADER` by hand
if either part of the upstream contract changes.

This pin is hand-maintained, not automatically drift-checked: a live fetch of the upstream
spec from this repo's CI can't actually authenticate — service-sessions is a private repo,
and the default `GITHUB_TOKEN` GitHub Actions provides is scoped to the repo the workflow
runs in, not other private repos in the org, regardless of `permissions:` settings on this
side. A prior version of this test attempted that live fetch and skipped unconditionally in
CI as a result — inert by construction, the opposite of the drift guard it claimed to be.
Actually detecting drift belongs on the service-sessions side, which already has read access
to its own spec — tracked as bechtleav360/avs.ai.idac.service-sessions#238 (a job there that
opens an issue/PR here when the relevant part of the contract changes).
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
import respx
from cachetools import TTLCache

from blueprint.agents.services.sessions.key_provider import SessionKeyProvider

# Transcribed by hand from service-sessions' docs/openapi.yaml rather than parsed from a
# checked-out copy — this repo has no dependency on service-sessions' sources or docs, and
# a hand-pin makes the "refresh this if the upstream contract changes" note above actually
# actionable (there is nothing to re-fetch automatically).
_PINNED_PARAMETERS: list[dict[str, Any]] = [
    {"name": "X-Agent-Id", "in": "header", "required": True, "schema": {"type": "string"}},
]
# From components.securitySchemes.ApiKey, not from the route's `parameters` block.
_PINNED_SECURITY_HEADER = "X-Api-Key"

# Added by bechtleav360/avs.ai.idac.service-sessions#326 (issue #198,
# `feat(auth)!: per-agent bearer identity on the agent-facing routes`): a second
# `securitySchemes` entry, `BearerAuth` (`type: http, scheme: bearer`, an HS256 JWT whose
# `sub` must equal the agent's `agent_id` and whose `caps` claim is the capability ceiling),
# applied via `security: [ApiKey: [], BearerAuth: []]` on this route. It rides in the standard
# `Authorization: Bearer <token>` header.
#
# It is *conditionally required* server-side, which is why this contract pin treats it as
# optional on the client: when the server has `auth.jwt_secret` configured the gate is ON and a
# missing/invalid bearer is 401/403; when it is unset the route still answers (the pre-gate
# state). The blueprint client mirrors that by sending the bearer only when a per-agent token is
# configured (`sessions_service.agent_token`) — so a token-less client stays byte-for-byte
# compatible with an ungated server, which is the whole point of the staged rollout.
_PINNED_BEARER_SECURITY_HEADER = "Authorization"
_PINNED_BEARER_SCHEME = "Bearer"

_JOB_REMOTE_URL = "http://sessions.local:8001"


def _required_headers() -> set[str]:
    return {p["name"] for p in _PINNED_PARAMETERS if p["in"] == "header" and p["required"]} | {_PINNED_SECURITY_HEADER}


def _make_job_provider(agent_token: str = "") -> SessionKeyProvider:
    provider = SessionKeyProvider()
    provider._source = "job"
    provider._remote_url = _JOB_REMOTE_URL
    provider._api_key = "sekrit"
    provider._agent_token = agent_token
    provider._agent_id = "agent-42"
    provider._cache = TTLCache(maxsize=100, ttl=60)
    return provider


class TestSessionKeyJobFetchMatchesPublishedContract:
    def test_pinned_parameters_declare_no_query_parameters(self) -> None:
        """Sanity-check the pin itself: the published contract has zero query params.

        If this ever fails, the upstream contract changed shape (e.g. `agent_id` moved back
        to the query string) and `_PINNED_PARAMETERS` needs a matching update before the
        request-shape assertion below means anything.
        """
        assert all(p["in"] != "query" for p in _PINNED_PARAMETERS)

    @respx.mock
    async def test_request_satisfies_pinned_contract(self) -> None:
        job_id = uuid4()
        route = respx.get(f"{_JOB_REMOTE_URL}/internal/jobs/{job_id}/session-key").mock(
            return_value=httpx.Response(200, json={"session_key": "job-secret"})
        )
        provider = _make_job_provider()

        await provider.get_session_key(uuid4(), job_id=job_id)

        request = route.calls.last.request
        for header_name in _required_headers():
            assert header_name in request.headers, f"contract requires {header_name!r} header, request has none"
        # The parameters block declares zero query parameters (checked above) — any query
        # string on the actual request is drift, not just the historical `?agent_id=...`
        # shape #94 hit.
        assert not dict(request.url.params), f"contract declares no query params, request sent: {dict(request.url.params)}"

    @respx.mock
    async def test_request_sends_bearer_satisfying_optional_scheme_when_token_configured(self) -> None:
        """When a per-agent token is configured, the request carries the optional
        `BearerAuth` scheme as `Authorization: Bearer <token>` *in addition to* the always-on
        `ApiKey`/`X-Agent-Id` headers — satisfying the post-#326 contract on a gated server
        (service-sessions#198/#326) without dropping anything the pre-gate contract required.
        """
        job_id = uuid4()
        route = respx.get(f"{_JOB_REMOTE_URL}/internal/jobs/{job_id}/session-key").mock(
            return_value=httpx.Response(200, json={"session_key": "job-secret"})
        )
        provider = _make_job_provider(agent_token="agent-jwt")

        await provider.get_session_key(uuid4(), job_id=job_id)

        request = route.calls.last.request
        # Every always-required header is still present.
        for header_name in _required_headers():
            assert header_name in request.headers, f"contract requires {header_name!r} header, request has none"
        # The optional bearer scheme is satisfied.
        assert request.headers.get(_PINNED_BEARER_SECURITY_HEADER) == f"{_PINNED_BEARER_SCHEME} agent-jwt"

    @respx.mock
    async def test_request_omits_bearer_when_no_token_configured_staying_pre_gate_compatible(self) -> None:
        """Backward-compat half of the optional scheme: with no token configured the request
        sends NO `Authorization` header at all, so it stays byte-for-byte compatible with an
        ungated server — exactly the pre-#326 contract, which is what lets bearer-capable
        agents roll out before the gate is flipped.
        """
        job_id = uuid4()
        route = respx.get(f"{_JOB_REMOTE_URL}/internal/jobs/{job_id}/session-key").mock(
            return_value=httpx.Response(200, json={"session_key": "job-secret"})
        )
        provider = _make_job_provider()  # no agent_token

        await provider.get_session_key(uuid4(), job_id=job_id)

        request = route.calls.last.request
        assert _PINNED_BEARER_SECURITY_HEADER not in request.headers
        # The pre-gate required headers are all still present and unchanged.
        for header_name in _required_headers():
            assert header_name in request.headers
