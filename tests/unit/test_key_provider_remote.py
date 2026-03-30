# tests/unit/test_key_provider_remote.py
import httpx
import pytest
import respx
from uuid import uuid4
from cachetools import TTLCache
from blueprint.agents.component.component import Component
from blueprint.agents.services.sessions.key_provider import SessionKeyProvider


@pytest.fixture(autouse=True)
def clear_registry():
    """Clear the component registry before each test to avoid duplicate-name errors."""
    if Component.shared_registry is not None:
        Component.shared_registry.clear_components()
    yield
    if Component.shared_registry is not None:
        Component.shared_registry.clear_components()


def make_provider(remote_url: str, api_key: str = "test-key") -> SessionKeyProvider:
    provider = SessionKeyProvider()
    provider._source = "remote"
    provider._remote_url = remote_url
    provider._api_key = api_key
    provider._cache = TTLCache(maxsize=100, ttl=60)
    return provider


@respx.mock
async def test_get_from_remote_returns_key():
    session_id = uuid4()
    remote_url = "http://email-monitor:8001/v1/sessions"
    respx.get(f"{remote_url}/{session_id}/key").mock(
        return_value=httpx.Response(200, json={"session_key": "abc123"})
    )

    provider = make_provider(remote_url)
    key = await provider.get_session_key(session_id)
    assert key == "abc123"


@respx.mock
async def test_get_from_remote_caches_key():
    session_id = uuid4()
    remote_url = "http://email-monitor:8001/v1/sessions"
    route = respx.get(f"{remote_url}/{session_id}/key").mock(
        return_value=httpx.Response(200, json={"session_key": "cached-key"})
    )

    provider = make_provider(remote_url)
    await provider.get_session_key(session_id)
    await provider.get_session_key(session_id)  # second call should use cache

    assert route.call_count == 1


@respx.mock
async def test_get_from_remote_raises_on_404():
    session_id = uuid4()
    remote_url = "http://email-monitor:8001/v1/sessions"
    respx.get(f"{remote_url}/{session_id}/key").mock(return_value=httpx.Response(404))

    provider = make_provider(remote_url)
    with pytest.raises(httpx.HTTPStatusError):
        await provider.get_session_key(session_id)
