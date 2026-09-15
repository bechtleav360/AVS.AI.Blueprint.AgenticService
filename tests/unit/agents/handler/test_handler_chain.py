"""Unit tests for HandlerChain."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from blueprint.agents.handler.handler_chain import (
    DUPLICATE_CONTEXT_KEY,
    IDEMPOTENCY_CACHE_NAMESPACE,
    HandlerChain,
    IdempotencyPolicy,
)
from blueprint.agents.models.events import GenericCloudEvent, HandlerResult
from tests.unit.agents.handler.conftest import StubHandler


@pytest.fixture
def chain(mock_registry: MagicMock, mock_config: MagicMock) -> HandlerChain:
    """HandlerChain with mocked registry (does not self-register).

    ``config.get`` returns the caller's default so unset keys read as unset rather than
    as a truthy MagicMock; the chain validates the type of ``idempotency_enabled``.
    """
    mock_config.get.side_effect = lambda key, default=None: default
    return HandlerChain()


def _wire_handlers(mock_registry: MagicMock, handlers: list) -> None:
    """Configure mock_registry.get_event_handler to return the given list."""
    mock_registry.get_event_handler.return_value = handlers


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    async def test_on_startup_resolves_idempotency_policy(self, chain: HandlerChain) -> None:
        await chain.on_startup()
        assert chain._policy == IdempotencyPolicy(enabled=False, ttl=0)

    async def test_on_shutdown_is_noop(self, chain: HandlerChain) -> None:
        await chain.on_shutdown()


# ---------------------------------------------------------------------------
# process — handler dispatch
# ---------------------------------------------------------------------------


class TestProcess:
    async def test_no_handlers_returns_none(self, chain: HandlerChain, mock_registry: MagicMock, cloud_event: GenericCloudEvent) -> None:
        _wire_handlers(mock_registry, [])
        result = await chain.process(cloud_event, {})
        assert result is None

    async def test_handler_that_declines_is_skipped(
        self, chain: HandlerChain, mock_registry: MagicMock, cloud_event: GenericCloudEvent
    ) -> None:
        _wire_handlers(mock_registry, [StubHandler(can_handle=False)])
        result = await chain.process(cloud_event, {})
        assert result is None

    async def test_handler_result_returned(self, chain: HandlerChain, mock_registry: MagicMock, cloud_event: GenericCloudEvent) -> None:
        expected = HandlerResult(event_type="out.event", data={"done": True})
        _wire_handlers(mock_registry, [StubHandler(result=expected)])
        result = await chain.process(cloud_event, {})
        assert result is expected

    async def test_handler_returning_none_passes_to_next(
        self, chain: HandlerChain, mock_registry: MagicMock, cloud_event: GenericCloudEvent
    ) -> None:
        second_result = HandlerResult(event_type="second.event", data={})
        _wire_handlers(
            mock_registry,
            [
                StubHandler(priority=10, result=None),
                StubHandler(priority=20, result=second_result),
            ],
        )
        result = await chain.process(cloud_event, {})
        assert result is second_result

    async def test_chain_stops_after_first_non_none_result(
        self, chain: HandlerChain, mock_registry: MagicMock, cloud_event: GenericCloudEvent
    ) -> None:
        first_result = HandlerResult(event_type="first.event", data={})
        second_handler = StubHandler(priority=20, result=HandlerResult(event_type="second.event", data={}))
        _wire_handlers(
            mock_registry,
            [
                StubHandler(priority=10, result=first_result),
                second_handler,
            ],
        )
        result = await chain.process(cloud_event, {})
        assert result is first_result

    async def test_handlers_executed_in_ascending_priority_order(
        self, chain: HandlerChain, mock_registry: MagicMock, cloud_event: GenericCloudEvent
    ) -> None:
        call_order: list[int] = []

        class OrderCapture(StubHandler):
            async def can_handle_event(self, event, context):
                call_order.append(self._priority)
                return False  # let all handlers run

        _wire_handlers(
            mock_registry,
            [
                OrderCapture(priority=30),
                OrderCapture(priority=10),
                OrderCapture(priority=20),
            ],
        )
        await chain.process(cloud_event, {})
        assert call_order == [10, 20, 30]

    async def test_handler_exception_is_reraised(
        self, chain: HandlerChain, mock_registry: MagicMock, cloud_event: GenericCloudEvent
    ) -> None:
        class BrokenHandler(StubHandler):
            async def handle_event(self, event, context):
                raise RuntimeError("handler exploded")

        _wire_handlers(mock_registry, [BrokenHandler()])
        with pytest.raises(RuntimeError, match="handler exploded"):
            await chain.process(cloud_event, {})


# ---------------------------------------------------------------------------
# Idempotency (P4, spec sec. 7.4)
# ---------------------------------------------------------------------------


class _StubCache:
    """In-memory stand-in for the registered CacheService, recording its calls."""

    def __init__(self) -> None:
        self.store: dict[str, Any] = {}
        self.namespaces: list[str] = []
        self.ttls: list[int | None] = []

    @staticmethod
    def _key(key: Any) -> str:
        return repr(sorted(key.items())) if isinstance(key, dict) else repr(key)

    def exists(self, key: Any, namespace: str = "default") -> bool:
        return self._key(key) in self.store

    def set(self, key: Any, value: Any, namespace: str = "default", ttl: int | None = None) -> None:
        self.store[self._key(key)] = value
        self.namespaces.append(namespace)
        self.ttls.append(ttl)

    def delete(self, key: Any, namespace: str = "default") -> bool:
        return self.store.pop(self._key(key), None) is not None


def _enable_dedup(mock_config: MagicMock, mock_registry: MagicMock, ttl: int = 60) -> _StubCache:
    """Turn dedup on with a working cache, and return that cache."""
    settings = {"idempotency_enabled": True, "idempotency_ttl": ttl}
    mock_config.get.side_effect = lambda key, default=None: settings.get(key, default)
    cache = _StubCache()
    mock_registry.has_cache.return_value = True
    mock_registry.cache_service = cache
    return cache


class TestIdempotencyDisabled:
    async def test_dedup_is_off_by_default(self, chain: HandlerChain, mock_registry: MagicMock, cloud_event: GenericCloudEvent) -> None:
        _wire_handlers(mock_registry, [StubHandler(result=None)])

        await chain.process(cloud_event, {})

        assert chain._policy == IdempotencyPolicy(enabled=False, ttl=0)

    async def test_repeat_delivery_dispatches_again_when_disabled(
        self, chain: HandlerChain, mock_registry: MagicMock, cloud_event: GenericCloudEvent
    ) -> None:
        seen: list[str] = []

        class Counting(StubHandler):
            async def can_handle_event(self, event, context):
                seen.append(event.id)
                return False

        _wire_handlers(mock_registry, [Counting()])

        await chain.process(cloud_event, {})
        await chain.process(cloud_event, {})

        assert seen == ["evt-001", "evt-001"]


class TestIdempotencyEnabled:
    async def test_same_event_delivered_twice_dispatches_once(
        self, chain: HandlerChain, mock_registry: MagicMock, mock_config: MagicMock, cloud_event: GenericCloudEvent
    ) -> None:
        _enable_dedup(mock_config, mock_registry)
        seen: list[str] = []

        class Counting(StubHandler):
            async def can_handle_event(self, event, context):
                seen.append(event.id)
                return False

        _wire_handlers(mock_registry, [Counting()])

        await chain.process(cloud_event, {})
        await chain.process(cloud_event, {})

        assert seen == ["evt-001"]

    async def test_duplicate_is_flagged_in_context_and_returns_none(
        self, chain: HandlerChain, mock_registry: MagicMock, mock_config: MagicMock, cloud_event: GenericCloudEvent
    ) -> None:
        _enable_dedup(mock_config, mock_registry)
        _wire_handlers(mock_registry, [StubHandler(result=HandlerResult(event_type="out", data={}))])

        first_context: dict[str, Any] = {}
        await chain.process(cloud_event, first_context)
        second_context: dict[str, Any] = {}
        result = await chain.process(cloud_event, second_context)

        assert result is None
        assert DUPLICATE_CONTEXT_KEY not in first_context
        assert second_context[DUPLICATE_CONTEXT_KEY] is True

    async def test_claim_is_written_with_the_configured_ttl_and_namespace(
        self, chain: HandlerChain, mock_registry: MagicMock, mock_config: MagicMock, cloud_event: GenericCloudEvent
    ) -> None:
        cache = _enable_dedup(mock_config, mock_registry, ttl=1500)
        _wire_handlers(mock_registry, [])

        await chain.process(cloud_event, {})

        assert cache.ttls == [1500]
        assert cache.namespaces == [IDEMPOTENCY_CACHE_NAMESPACE]

    async def test_same_id_from_another_source_is_not_a_duplicate(
        self, chain: HandlerChain, mock_registry: MagicMock, mock_config: MagicMock, cloud_event: GenericCloudEvent
    ) -> None:
        """The CloudEvents id is unique only within a source, so the key carries both."""
        _enable_dedup(mock_config, mock_registry)
        seen: list[str] = []

        class Counting(StubHandler):
            async def can_handle_event(self, event, context):
                seen.append(event.source)
                return False

        _wire_handlers(mock_registry, [Counting()])
        other = GenericCloudEvent(id="evt-001", type="test.event", source="other-source")

        await chain.process(cloud_event, {})
        await chain.process(other, {})

        assert seen == ["test-source", "other-source"]

    async def test_failed_dispatch_releases_the_claim(
        self, chain: HandlerChain, mock_registry: MagicMock, mock_config: MagicMock, cloud_event: GenericCloudEvent
    ) -> None:
        """A failure naks, so the redelivery must be allowed to run rather than be deduped."""
        cache = _enable_dedup(mock_config, mock_registry)
        attempts: list[str] = []

        class Broken(StubHandler):
            async def handle_event(self, event, context):
                attempts.append(event.id)
                raise RuntimeError("handler exploded")

        _wire_handlers(mock_registry, [Broken()])

        with pytest.raises(RuntimeError):
            await chain.process(cloud_event, {})
        assert cache.store == {}

        with pytest.raises(RuntimeError):
            await chain.process(cloud_event, {})
        assert attempts == ["evt-001", "evt-001"]

    async def test_event_without_a_source_is_dispatched_untracked(
        self, chain: HandlerChain, mock_registry: MagicMock, mock_config: MagicMock
    ) -> None:
        cache = _enable_dedup(mock_config, mock_registry)
        _wire_handlers(mock_registry, [])
        event = GenericCloudEvent.model_construct(id="evt-002", type="test.event", source="")

        await chain.process(event, {})

        assert cache.store == {}


class TestIdempotencyPolicyResolution:
    async def test_enabled_without_ttl_fails_startup(self, chain: HandlerChain, mock_registry: MagicMock, mock_config: MagicMock) -> None:
        mock_config.get.side_effect = lambda key, default=None: True if key == "idempotency_enabled" else default

        with pytest.raises(ValueError, match="idempotency_ttl"):
            await chain.on_startup()

    async def test_non_positive_ttl_fails_startup(self, chain: HandlerChain, mock_registry: MagicMock, mock_config: MagicMock) -> None:
        settings = {"idempotency_enabled": True, "idempotency_ttl": 0}
        mock_config.get.side_effect = lambda key, default=None: settings.get(key, default)

        with pytest.raises(ValueError, match="greater than 0"):
            await chain.on_startup()

    async def test_non_numeric_ttl_fails_startup(self, chain: HandlerChain, mock_registry: MagicMock, mock_config: MagicMock) -> None:
        settings = {"idempotency_enabled": True, "idempotency_ttl": "soon"}
        mock_config.get.side_effect = lambda key, default=None: settings.get(key, default)

        with pytest.raises(ValueError, match="must be an integer"):
            await chain.on_startup()

    async def test_enabled_without_a_cache_fails_startup(
        self, chain: HandlerChain, mock_registry: MagicMock, mock_config: MagicMock
    ) -> None:
        settings = {"idempotency_enabled": True, "idempotency_ttl": 60}
        mock_config.get.side_effect = lambda key, default=None: settings.get(key, default)
        mock_registry.has_cache.return_value = False

        with pytest.raises(ValueError, match="no cache is registered"):
            await chain.on_startup()

    async def test_non_boolean_enabled_fails_startup(self, chain: HandlerChain, mock_registry: MagicMock, mock_config: MagicMock) -> None:
        mock_config.get.side_effect = lambda key, default=None: 3 if key == "idempotency_enabled" else default

        with pytest.raises(ValueError, match="must be a boolean"):
            await chain.on_startup()

    async def test_enabled_as_a_string_is_accepted(self, chain: HandlerChain, mock_registry: MagicMock, mock_config: MagicMock) -> None:
        """Environment variables deliver booleans as text."""
        settings = {"idempotency_enabled": "true", "idempotency_ttl": "900"}
        mock_config.get.side_effect = lambda key, default=None: settings.get(key, default)
        mock_registry.has_cache.return_value = True

        await chain.on_startup()

        assert chain._policy == IdempotencyPolicy(enabled=True, ttl=900)
