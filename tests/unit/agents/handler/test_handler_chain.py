"""Unit tests for HandlerChain."""

from unittest.mock import MagicMock

import pytest

from blueprint.agents.handler.handler_chain import HandlerChain
from blueprint.agents.models.events import GenericCloudEvent, HandlerResult
from tests.unit.agents.handler.conftest import StubHandler


@pytest.fixture
def chain(mock_registry: MagicMock, mock_config: MagicMock) -> HandlerChain:
    """HandlerChain with mocked registry (does not self-register)."""
    return HandlerChain()


def _wire_handlers(mock_registry: MagicMock, handlers: list) -> None:
    """Configure mock_registry.get_event_handler to return the given list."""
    mock_registry.get_event_handler.return_value = handlers


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    async def test_on_startup_is_noop(self, chain: HandlerChain) -> None:
        await chain.on_startup()

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
