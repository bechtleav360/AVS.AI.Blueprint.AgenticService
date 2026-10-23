"""ReadingHandler translates; ReadingService decides against the run's site threshold."""

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from blueprint.agents.models.events import GenericCloudEvent

from src.handlers.reading_handler import ReadingHandler
from src.models.domain_models import Alert, Reading
from src.services.reading_service import ReadingService
from src.sites import SiteSettings, enter_site, leave_site


@contextmanager
def site(name: str, threshold: float):
    token = enter_site(SiteSettings(name=name, alert_threshold=threshold))
    try:
        yield
    finally:
        leave_site(token)


def _event(value: float) -> GenericCloudEvent:
    return GenericCloudEvent(id="evt-1", type="reading.recorded", source="/sites/site_a", data={"sensor_id": "s1", "value": value})


@pytest.fixture
def service() -> ReadingService:
    svc = object.__new__(ReadingService)
    svc._cache = MagicMock()
    return svc


class TestService:
    async def test_within_the_threshold_is_no_alert(self, service):
        with site("site_a", 50.0):
            assert await service.on_reading(Reading(sensor_id="s1", value=50.0), event_id="e1") is None
        service._cache.set.assert_not_called()

    async def test_above_the_threshold_is_an_alert_stored_under_the_event_id(self, service):
        with site("site_b", 80.0):
            alert = await service.on_reading(Reading(sensor_id="s1", value=81.0), event_id="e2")
        assert alert == Alert(sensor_id="s1", value=81.0, threshold=80.0, site="site_b")
        assert service._cache.set.call_args.args[0] == "e2"

    async def test_the_same_value_differs_by_site(self, service):
        with site("site_a", 50.0):
            assert await service.on_reading(Reading(sensor_id="s1", value=60.0), event_id="e3") is not None
        with site("site_b", 80.0):
            assert await service.on_reading(Reading(sensor_id="s1", value=60.0), event_id="e4") is None

    async def test_outside_a_sites_run_there_is_no_threshold(self, service):
        with pytest.raises(LookupError):
            await service.on_reading(Reading(sensor_id="s1", value=1.0), event_id="e5")


@pytest.fixture
def handler() -> ReadingHandler:
    h = object.__new__(ReadingHandler)
    h._priority = 10
    h._service = MagicMock()
    h._service.on_reading = AsyncMock(return_value=None)
    return h


class TestHandler:
    async def test_routes_on_the_type_and_declares_its_subject(self, handler):
        assert handler.get_subscribed_topics() == ["readings.>"]
        assert handler.get_handled_event_types() == ["reading.recorded"]
        assert await handler.can_handle_event(_event(1.0), {}) is True

    async def test_no_alert_is_a_skip(self, handler):
        result = await handler.handle_event(_event(1.0), {})
        assert result.is_skipped
        handler._service.on_reading.assert_awaited_once_with(Reading(sensor_id="s1", value=1.0), event_id="evt-1")

    async def test_an_alert_is_returned_unpublished(self, handler):
        handler._service.on_reading.return_value = Alert(sensor_id="s1", value=99.0, threshold=50.0, site="site_a")
        result = await handler.handle_event(_event(99.0), {})
        assert result.event_type is None
        assert result.data["site"] == "site_a"
