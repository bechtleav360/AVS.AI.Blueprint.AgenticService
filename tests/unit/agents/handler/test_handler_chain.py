"""Unit tests for HandlerChain."""

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

from blueprint.agents.clients.io.nats_connections import NATS_CONNECTION_CONTEXT_KEY
from blueprint.agents.handler.handler_chain import (
    CLAIMED_CONTEXT_KEY,
    CONNECTION_CONTEXT_KEY,
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

    async def test_skipped_result_stops_the_chain_and_offers_the_event_to_nobody_else(
        self, chain: HandlerChain, mock_registry: MagicMock, cloud_event: GenericCloudEvent
    ) -> None:
        """A skip is the selected handler's answer, not a decline: the next handler must not run.

        Regression guard for the difference to ``None``, which does pass the event on.
        """
        asked: list[int] = []

        class Recording(StubHandler):
            async def can_handle_event(self, event, context):
                asked.append(self._priority)
                return True

        skip = HandlerResult.skipped("status unchanged")
        _wire_handlers(mock_registry, [Recording(priority=10, result=skip), Recording(priority=20, result=HandlerResult(event_type="x"))])
        result = await chain.process(cloud_event, {})
        assert result is skip
        assert asked == [10]

    async def test_skipped_result_logs_its_reason_at_info_and_no_warning(
        self,
        chain: HandlerChain,
        mock_registry: MagicMock,
        cloud_event: GenericCloudEvent,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A skip is an ordinary outcome: its reason at INFO, never the no-handler WARNING."""
        _wire_handlers(mock_registry, [StubHandler(result=HandlerResult.skipped("status unchanged"))])
        with caplog.at_level("DEBUG", logger="blueprint.agents.handler.handler_chain"):
            await chain.process(cloud_event, {})
        skipped = [r for r in caplog.records if "skipped event" in r.getMessage()]
        assert [r.levelname for r in skipped] == ["INFO"]
        assert "status unchanged" in skipped[0].getMessage()
        assert not [r for r in caplog.records if r.levelname == "WARNING"]

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

    async def test_a_handler_failure_is_raised_not_logged(
        self, chain: HandlerChain, mock_registry: MagicMock, cloud_event: GenericCloudEvent, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The transport edge logs it with its disposition; logging here too doubled every failure."""

        class BrokenHandler(StubHandler):
            async def handle_event(self, event, context):
                raise RuntimeError("handler exploded")

        _wire_handlers(mock_registry, [BrokenHandler()])
        with caplog.at_level("ERROR", logger="blueprint.agents.handler.handler_chain"), pytest.raises(RuntimeError):
            await chain.process(cloud_event, {})
        assert caplog.records == []


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

    def claim(self, key: Any, value: Any, namespace: str = "default", ttl: int | None = None) -> bool:
        if self.exists(key, namespace):
            return False
        self.set(key, value, namespace=namespace, ttl=ttl)
        return True


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
    async def test_the_claim_is_one_atomic_call(
        self, chain: HandlerChain, mock_registry: MagicMock, mock_config: MagicMock, cloud_event: GenericCloudEvent
    ) -> None:
        """#6 -- exists() then set() let two replicas both pass; the atomic claim decides alone.

        Simulates the race window: exists() still says "absent", but another replica's claim won.
        """
        cache = _enable_dedup(mock_config, mock_registry)
        cache.exists = lambda key, namespace="default": False  # type: ignore[method-assign]
        cache.claim = lambda key, value, namespace="default", ttl=None: False  # type: ignore[method-assign]
        seen: list[str] = []

        class Counting(StubHandler):
            async def can_handle_event(self, event, context):
                seen.append(event.id)
                return False

        _wire_handlers(mock_registry, [Counting()])

        await chain.process(cloud_event, {})

        assert seen == []

    async def test_release_after_a_successful_dispatch_lets_the_redelivery_run(
        self, chain: HandlerChain, mock_registry: MagicMock, mock_config: MagicMock, cloud_event: GenericCloudEvent
    ) -> None:
        """#1 -- a result that failed to publish fails the delivery after the chain kept its claim."""
        _enable_dedup(mock_config, mock_registry)
        seen: list[str] = []

        class Counting(StubHandler):
            async def can_handle_event(self, event, context):
                seen.append(event.id)
                return False

        _wire_handlers(mock_registry, [Counting()])

        context: dict[str, Any] = {}
        await chain.process(cloud_event, context)
        await chain.release(cloud_event, context)
        await chain.process(cloud_event, {})

        assert seen == ["evt-001", "evt-001"]

    async def test_release_with_dedup_off_is_a_no_op(
        self, chain: HandlerChain, mock_registry: MagicMock, cloud_event: GenericCloudEvent
    ) -> None:
        _wire_handlers(mock_registry, [StubHandler(result=None)])
        context: dict[str, Any] = {}
        await chain.process(cloud_event, context)

        await chain.release(cloud_event, context)

        assert CLAIMED_CONTEXT_KEY not in context
        mock_registry.cache_service.delete.assert_not_called()

    async def test_a_duplicate_releases_nothing(
        self, chain: HandlerChain, mock_registry: MagicMock, mock_config: MagicMock, cloud_event: GenericCloudEvent
    ) -> None:
        """B1 -- the marker a duplicate ran into is the first delivery's; dropping it would let a third copy run."""
        cache = _enable_dedup(mock_config, mock_registry)
        _wire_handlers(mock_registry, [StubHandler(result=None)])
        first: dict[str, Any] = {}
        await chain.process(cloud_event, first)
        duplicate: dict[str, Any] = {}
        await chain.process(cloud_event, duplicate)

        await chain.release(cloud_event, duplicate)

        assert first[CLAIMED_CONTEXT_KEY] is True
        assert CLAIMED_CONTEXT_KEY not in duplicate
        assert len(cache.store) == 1

    async def test_a_released_claim_is_released_once(
        self, chain: HandlerChain, mock_registry: MagicMock, mock_config: MagicMock, cloud_event: GenericCloudEvent
    ) -> None:
        """Every exit path may release; only the first one deletes, so a later claim by a redelivery survives."""
        cache = _enable_dedup(mock_config, mock_registry)
        _wire_handlers(mock_registry, [StubHandler(result=None)])
        context: dict[str, Any] = {}
        await chain.process(cloud_event, context)
        await chain.release(cloud_event, context)
        await chain.process(cloud_event, {})  # the redelivery claims again

        await chain.release(cloud_event, context)

        assert len(cache.store) == 1

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

    async def test_the_same_event_on_two_named_connections_is_not_a_duplicate(
        self, chain: HandlerChain, mock_registry: MagicMock, mock_config: MagicMock, cloud_event: GenericCloudEvent
    ) -> None:
        """T1 -- each connection is a data source of its own; one must not suppress another's event."""
        _enable_dedup(mock_config, mock_registry)
        seen: list[str] = []

        class Counting(StubHandler):
            async def can_handle_event(self, event, context):
                seen.append(context[CONNECTION_CONTEXT_KEY])
                return False

        _wire_handlers(mock_registry, [Counting()])

        await chain.process(cloud_event, {CONNECTION_CONTEXT_KEY: "A"})
        await chain.process(cloud_event, {CONNECTION_CONTEXT_KEY: "B"})
        await chain.process(cloud_event, {CONNECTION_CONTEXT_KEY: "A"})

        assert seen == ["A", "B"]

    async def test_a_named_connections_claim_is_released_under_its_own_key(
        self, chain: HandlerChain, mock_registry: MagicMock, mock_config: MagicMock, cloud_event: GenericCloudEvent
    ) -> None:
        cache = _enable_dedup(mock_config, mock_registry)
        _wire_handlers(mock_registry, [StubHandler(result=None)])
        on_a: dict[str, Any] = {CONNECTION_CONTEXT_KEY: "A"}
        await chain.process(cloud_event, on_a)
        await chain.process(cloud_event, {CONNECTION_CONTEXT_KEY: "B"})

        await chain.release(cloud_event, on_a)

        assert list(cache.store) == [_StubCache._key({"id": "evt-001", "source": "test-source", "connection": "B"})]

    async def test_the_default_connection_keeps_the_two_part_key(
        self, chain: HandlerChain, mock_registry: MagicMock, mock_config: MagicMock, cloud_event: GenericCloudEvent
    ) -> None:
        """Markers written before connections were part of the key still match after an upgrade."""
        cache = _enable_dedup(mock_config, mock_registry)
        _wire_handlers(mock_registry, [StubHandler(result=None)])

        await chain.process(cloud_event, {})

        assert list(cache.store) == [_StubCache._key({"id": "evt-001", "source": "test-source"})]

    def test_the_context_key_is_the_one_the_nats_endpoint_sets(self) -> None:
        assert CONNECTION_CONTEXT_KEY == NATS_CONNECTION_CONTEXT_KEY

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

    async def test_a_cancelled_dispatch_releases_the_claim(
        self, chain: HandlerChain, mock_registry: MagicMock, mock_config: MagicMock, cloud_event: GenericCloudEvent
    ) -> None:
        """B1 -- a handler timeout or a shutdown ends the run with CancelledError, a BaseException."""
        cache = _enable_dedup(mock_config, mock_registry)

        class Cancelled(StubHandler):
            async def handle_event(self, event, context):
                raise asyncio.CancelledError

        _wire_handlers(mock_registry, [Cancelled()])

        with pytest.raises(asyncio.CancelledError):
            await chain.process(cloud_event, {})

        assert cache.store == {}

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


# ---------------------------------------------------------------------------
# A standalone agent logs what v0.8.1 logged
# ---------------------------------------------------------------------------


class TestStandaloneLogLines:
    async def test_no_handler_line(
        self, chain: HandlerChain, mock_registry: MagicMock, cloud_event: GenericCloudEvent, caplog: pytest.LogCaptureFixture
    ) -> None:
        _wire_handlers(mock_registry, [StubHandler(result=None)])
        with caplog.at_level("WARNING", logger="blueprint.agents.handler.handler_chain"):
            await chain.process(cloud_event, {})
        assert caplog.messages == [f"No handler processed event '{cloud_event.type}'"]


class TestTheCacheIsCalledOffTheEventLoop:
    """S7 -- claim and delete block (a Redis round trip, a disk write); on the loop every delivery waited."""

    async def test_claim_and_delete_run_in_another_thread(
        self, chain: HandlerChain, mock_registry: MagicMock, mock_config: MagicMock, cloud_event: GenericCloudEvent
    ) -> None:
        import threading

        cache = _enable_dedup(mock_config, mock_registry)
        threads: list[int] = []
        claim, delete = cache.claim, cache.delete
        cache.claim = lambda *a, **k: threads.append(threading.get_ident()) or claim(*a, **k)  # type: ignore[method-assign]
        cache.delete = lambda *a, **k: threads.append(threading.get_ident()) or delete(*a, **k)  # type: ignore[method-assign]
        _wire_handlers(mock_registry, [StubHandler(result=None)])
        context: dict[str, Any] = {}

        await chain.process(cloud_event, context)
        await chain.release(cloud_event, context)

        assert len(threads) == 2
        assert threading.get_ident() not in threads


class TestDedupWithoutAHeartbeatWarns:
    """S6, plan D4 -- a redelivery while the first run still goes is skipped as a duplicate; the heartbeat prevents it."""

    @staticmethod
    def _settings(mock_config: MagicMock, **values: Any) -> None:
        settings = {"idempotency_enabled": True, "idempotency_ttl": 60, **values}
        mock_config.get.side_effect = lambda key, default=None: settings.get(key, default)

    async def test_nats_with_the_heartbeat_off_warns(
        self, chain: HandlerChain, mock_registry: MagicMock, mock_config: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        self._settings(mock_config, event_bus="nats", nats_heartbeat_enabled=False)
        _wire_handlers(mock_registry, [])
        with caplog.at_level("WARNING"):
            await chain.on_startup()
        assert "nats_heartbeat_enabled = false" in caplog.text

    async def test_an_environment_string_false_warns_too(
        self, chain: HandlerChain, mock_registry: MagicMock, mock_config: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An environment override arrives as text; 'false' must count as off, as the NATS client reads it."""
        self._settings(mock_config, event_bus="nats", nats_heartbeat_enabled="false")
        _wire_handlers(mock_registry, [])
        with caplog.at_level("WARNING"):
            await chain.on_startup()
        assert "nats_heartbeat_enabled = false" in caplog.text

    async def test_dapr_warns_naming_the_app_call_timeout(
        self, chain: HandlerChain, mock_registry: MagicMock, mock_config: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        self._settings(mock_config, event_bus="dapr")
        _wire_handlers(mock_registry, [])
        with caplog.at_level("WARNING"):
            await chain.on_startup()
        assert "app-call timeout" in caplog.text

    async def test_nats_with_the_heartbeat_on_is_quiet(
        self, chain: HandlerChain, mock_registry: MagicMock, mock_config: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        self._settings(mock_config, event_bus="nats")
        _wire_handlers(mock_registry, [])
        with caplog.at_level("WARNING"):
            await chain.on_startup()
        assert [record for record in caplog.records if record.levelname == "WARNING"] == []
