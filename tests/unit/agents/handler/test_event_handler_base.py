"""Unit tests for EventHandlerBase."""

from unittest.mock import MagicMock


from blueprint.agents.models.events import GenericCloudEvent, HandlerResult
from tests.unit.agents.handler.conftest import StubHandler

# ---------------------------------------------------------------------------
# __init__ — priority storage
# ---------------------------------------------------------------------------


class TestInit:
    def test_default_priority_is_100(self, mock_registry: MagicMock) -> None:
        handler = StubHandler()
        assert handler._priority == 100

    def test_custom_priority_stored(self, mock_registry: MagicMock) -> None:
        handler = StubHandler(priority=10)
        assert handler._priority == 10


# ---------------------------------------------------------------------------
# can_handle — traced wrapper delegates to can_handle_event
# ---------------------------------------------------------------------------


class TestCanHandle:
    async def test_returns_true_when_can_handle_event_returns_true(self, mock_registry: MagicMock, cloud_event: GenericCloudEvent) -> None:
        handler = StubHandler(can_handle=True)
        assert await handler.can_handle(cloud_event, {}) is True

    async def test_returns_false_when_can_handle_event_returns_false(
        self, mock_registry: MagicMock, cloud_event: GenericCloudEvent
    ) -> None:
        handler = StubHandler(can_handle=False)
        assert await handler.can_handle(cloud_event, {}) is False


# ---------------------------------------------------------------------------
# handle — traced wrapper; result pass-through
# ---------------------------------------------------------------------------


class TestHandle:
    async def test_handler_result_returned_as_is(self, mock_registry: MagicMock, cloud_event: GenericCloudEvent) -> None:
        hr = HandlerResult(event_type="out.event", data={"x": 1})
        handler = StubHandler(result=hr)
        result = await handler.handle(cloud_event, {})
        assert result is hr

    async def test_list_of_handler_results_returned_as_is(self, mock_registry: MagicMock, cloud_event: GenericCloudEvent) -> None:
        hrs = [HandlerResult(event_type="a"), HandlerResult(event_type="b")]
        handler = StubHandler(result=hrs)
        result = await handler.handle(cloud_event, {})
        assert result is hrs

    async def test_dict_result_returned_as_is(self, mock_registry: MagicMock, cloud_event: GenericCloudEvent) -> None:
        payload = {"key": "value"}
        handler = StubHandler(result=payload)
        result = await handler.handle(cloud_event, {})
        assert result is payload

    async def test_none_result_returned_as_is(self, mock_registry: MagicMock, cloud_event: GenericCloudEvent) -> None:
        handler = StubHandler(result=None)
        assert await handler.handle(cloud_event, {}) is None


# ---------------------------------------------------------------------------
# get_published_event_types — default implementation
# ---------------------------------------------------------------------------


class TestGetPublishedEventTypes:
    def test_default_returns_none(self, mock_registry: MagicMock) -> None:
        handler = StubHandler()
        assert handler.get_published_event_types() is None


# ---------------------------------------------------------------------------
# get_subscribed_topics — default implementation
# ---------------------------------------------------------------------------


class TestGetSubscribedTopics:
    def test_default_returns_empty_list(self, mock_registry: MagicMock) -> None:
        handler = StubHandler()
        assert handler.get_subscribed_topics() == []


# ---------------------------------------------------------------------------
# __lt__ — priority-based sorting support
# ---------------------------------------------------------------------------


class TestLessThan:
    def test_lower_priority_value_is_less_than_higher(self, mock_registry: MagicMock) -> None:
        high = StubHandler(priority=10)
        low = StubHandler(priority=50)
        assert high < low

    def test_higher_priority_value_is_not_less_than_lower(self, mock_registry: MagicMock) -> None:
        high = StubHandler(priority=10)
        low = StubHandler(priority=50)
        assert not (low < high)

    def test_equal_priority_is_not_less_than(self, mock_registry: MagicMock) -> None:
        a = StubHandler(priority=20)
        b = StubHandler(priority=20)
        assert not (a < b)

    def test_sorted_orders_by_ascending_priority_value(self, mock_registry: MagicMock) -> None:
        handlers = [StubHandler(priority=30), StubHandler(priority=10), StubHandler(priority=20)]
        ordered = sorted(handlers)
        priorities = [h._priority for h in ordered]
        assert priorities == [10, 20, 30]
