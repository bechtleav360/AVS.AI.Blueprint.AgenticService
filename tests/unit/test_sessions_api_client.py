# tests/unit/test_sessions_api_client.py
import httpx
import pytest
import respx
from uuid import uuid4

from blueprint.agents.component.component import Component
from blueprint.agents.services.sessions.api_client import SessionsApiClient


@pytest.fixture(autouse=True)
def clear_registry():
    """Clear the component registry before each test to avoid duplicate-name errors."""
    if Component.shared_registry is not None:
        Component.shared_registry.clear_components()
    yield
    if Component.shared_registry is not None:
        Component.shared_registry.clear_components()


def make_client(base_url: str = "http://sessions:8000", api_key: str = "test-key") -> SessionsApiClient:
    client = SessionsApiClient()
    client._base_url = base_url
    client._api_key = api_key
    client._client = httpx.AsyncClient(
        timeout=httpx.Timeout(30.0),
        headers={"X-Api-Key": api_key},
    )
    return client


@respx.mock
async def test_start_job_sends_session_key():
    session_id = uuid4()
    job_id = uuid4()
    base_url = "http://sessions:8000"

    route = respx.post(f"{base_url}/sessions/{session_id}/jobs/{job_id}/start").mock(
        return_value=httpx.Response(200, json={"id": str(job_id), "status": "running"})
    )

    client = make_client(base_url)
    result = await client.start_job(session_id, job_id, "my-agent", "my-session-key")

    assert route.called
    request = route.calls[0].request
    assert request.headers.get("x-session-key") == "my-session-key"
    assert result["status"] == "running"


@respx.mock
async def test_get_job_detail_sends_session_key():
    session_id = uuid4()
    job_id = uuid4()
    base_url = "http://sessions:8000"

    route = respx.get(f"{base_url}/sessions/{session_id}/jobs/{job_id}").mock(
        return_value=httpx.Response(200, json={"id": str(job_id), "payload": {"key": "val"}})
    )

    client = make_client(base_url)
    result = await client.get_job_detail(session_id, job_id, "my-session-key")

    assert route.called
    request = route.calls[0].request
    assert request.headers.get("x-session-key") == "my-session-key"
    assert result["payload"]["key"] == "val"
