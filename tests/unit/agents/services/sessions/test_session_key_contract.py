"""Contract test: `SessionKeyProvider`'s job-scoped fetch vs. service-sessions' published
OpenAPI contract for `GET /internal/jobs/{job_id}/session-key` (#94 follow-up).

Both the pre-#94 and post-#94 unit tests in ``test_key_provider.py`` only ever assert what
*this* client believes the wire contract is (first a query param, now a header) — never what
the server actually requires, so neither generation would have caught #94's bug (every call
got a guaranteed 422). This test instead pins the contract straight from service-sessions'
own committed, drift-guarded spec (that repo's ``tests/integration/test_openapi_contract_parity.py``
fails its build if the spec and the generated schema disagree), and asserts the request this
client actually sends satisfies it.

Lives under ``tests/unit/`` rather than ``tests/integration/`` — despite being a contract
pin — because it has no external dependency (pure ``respx``, same as the rest of
``test_key_provider.py``) and ``ci.yml`` only ever runs ``pytest tests/unit``; a copy under
``tests/integration/`` would never actually execute in CI (review, PR #95).

Pinned from ``bechtleav360/avs.ai.idac.service-sessions`` @ ``d5ee98f0dd29679ca52db753d2481858ae5cc509``,
``docs/openapi.yaml``, path ``/internal/jobs/{job_id}/session-key``, from two distinct parts of
the spec: ``X-Agent-Id`` is a route-level ``parameters`` entry; ``X-Api-Key`` is not a
``parameters`` entry at all — it's the global `ApiKey` `securitySchemes` entry
(`type: apiKey, in: header, name: X-Api-Key`), applied via `security: [ApiKey: []]` both
globally and on this route (review, PR #95: the previous version of this pin listed both
under one `parameters` list, which misrepresented where `X-Api-Key` actually comes from).
Refresh `_PINNED_PARAMETERS`/`_PINNED_SECURITY_HEADER` (and the commit SHA above) if either
part of the upstream contract changes.
"""

from __future__ import annotations

import os
from typing import Any
from uuid import uuid4

import httpx
import pytest
import respx
import yaml
from cachetools import TTLCache

from blueprint.agents.services.sessions.key_provider import SessionKeyProvider

_UPSTREAM_REPO = "bechtleav360/avs.ai.idac.service-sessions"
_UPSTREAM_SHA = "d5ee98f0dd29679ca52db753d2481858ae5cc509"
_UPSTREAM_PATH = "docs/openapi.yaml"
_UPSTREAM_ROUTE = "/internal/jobs/{job_id}/session-key"

# Transcribed by hand rather than parsed from a checked-out copy of the YAML — this repo
# has no dependency on service-sessions' sources or docs, and a hand-pin makes the "refresh
# this if the upstream contract changes" note above actually actionable (there is nothing to
# re-fetch automatically).
_PINNED_PARAMETERS: list[dict[str, Any]] = [
    {"name": "X-Agent-Id", "in": "header", "required": True, "schema": {"type": "string"}},
]
# From components.securitySchemes.ApiKey, not from the route's `parameters` block.
_PINNED_SECURITY_HEADER = "X-Api-Key"

_JOB_REMOTE_URL = "http://sessions.local:8001"


def _required_headers() -> set[str]:
    return {p["name"] for p in _PINNED_PARAMETERS if p["in"] == "header" and p["required"]} | {_PINNED_SECURITY_HEADER}


def _fetch_upstream_spec() -> dict[str, Any] | None:
    """Fetch the pinned commit's `openapi.yaml` from GitHub, or `None` if unreachable.

    service-sessions is a private repo, so this needs a token with read access — uses
    `GITHUB_TOKEN`/`GH_TOKEN` from the environment if set (Actions always provides
    `GITHUB_TOKEN` to a job; whether it can read *another* private repo in the org is a
    separate org-policy setting this test can't control or verify). Any failure to reach
    or read the spec — no token, no cross-repo grant, network down, repo/path renamed —
    is a skip, not a failure: this test's job is to catch upstream *contract* drift, not
    to gate the build on network/infra availability it doesn't own.
    """
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    headers = {"Accept": "application/vnd.github.raw+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"https://api.github.com/repos/{_UPSTREAM_REPO}/contents/{_UPSTREAM_PATH}?ref={_UPSTREAM_SHA}"
    try:
        response = httpx.get(url, headers=headers, timeout=10.0)
        response.raise_for_status()
    except httpx.HTTPError:
        return None
    return yaml.safe_load(response.text)


def _make_job_provider() -> SessionKeyProvider:
    provider = SessionKeyProvider()
    provider._source = "job"
    provider._remote_url = _JOB_REMOTE_URL
    provider._api_key = "sekrit"
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

    def test_pin_matches_live_upstream_spec(self) -> None:
        """Catches the drift direction the tests above can't: service-sessions changing
        its published contract without this pin being updated to match (review, PR #95
        — the hand-copied pin alone only ever catches *this client* drifting from itself).
        Skips, rather than fails, when the upstream spec can't be reached (see
        `_fetch_upstream_spec`) — a mismatch is a real failure; unreachable infra isn't.
        """
        spec = _fetch_upstream_spec()
        if spec is None:
            pytest.skip(
                "Could not reach upstream service-sessions openapi.yaml (no token/cross-repo access, or network) — pin not verified this run."
            )

        # Compare only the wire-relevant keys — `description` is documentation, not
        # contract, and the pin deliberately doesn't carry it (see comment above it).
        wire_keys = {"name", "in", "required", "schema"}
        live_params = [
            {k: v for k, v in p.items() if k in wire_keys}
            for p in spec["paths"][_UPSTREAM_ROUTE]["get"]["parameters"]
            if p["in"] == "header"
        ]
        assert live_params == _PINNED_PARAMETERS, (
            f"service-sessions' published header parameters for {_UPSTREAM_ROUTE} no longer "
            f"match the pin.\nlive: {live_params}\npinned: {_PINNED_PARAMETERS}"
        )

        live_security_header = spec["components"]["securitySchemes"].get("ApiKey", {}).get("name")
        assert live_security_header == _PINNED_SECURITY_HEADER, (
            f"service-sessions' ApiKey securityScheme header changed: live={live_security_header!r}, pinned={_PINNED_SECURITY_HEADER!r}"
        )
