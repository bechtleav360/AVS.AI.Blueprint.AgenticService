"""Detecting a blocked event loop, the one group-wide failure the process can see itself."""

import asyncio
import logging
from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest

from blueprint.agents.io.telemetry.inflight import IN_FLIGHT
from blueprint.agents.io.telemetry.loop_watchdog import DEBUG_KEY, LoopWatchdog, configure_loop_debug
from blueprint.agents.io.telemetry.providers import reset_providers


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    IN_FLIGHT.reset()
    reset_providers()
    yield
    IN_FLIGHT.reset()
    reset_providers()
    asyncio.get_event_loop_policy()


def _config(**values: object) -> MagicMock:
    config = MagicMock()
    config.get.side_effect = lambda key, default=None: values.get(key, default)
    return config


class TestDebugMode:
    async def test_development_turns_asyncio_debug_on(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            assert configure_loop_debug(_config(), development=True) is True
            assert loop.get_debug() is True
        finally:
            loop.set_debug(False)

    async def test_production_leaves_it_off(self) -> None:
        assert configure_loop_debug(_config(), development=False) is False
        assert asyncio.get_running_loop().get_debug() is False

    async def test_production_can_ask_for_it(self) -> None:
        """The exact answer is available in production; it just costs enough to be a decision."""
        loop = asyncio.get_running_loop()
        try:
            assert configure_loop_debug(_config(**{DEBUG_KEY: True}), development=False) is True
            assert loop.get_debug() is True
        finally:
            loop.set_debug(False)

    async def test_the_slow_callback_threshold_is_configurable(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            configure_loop_debug(_config(event_loop_slow_callback_seconds=0.5), development=True)
            assert loop.slow_callback_duration == 0.5
        finally:
            loop.set_debug(False)
            loop.slow_callback_duration = 0.1


class TestWatchdog:
    async def test_it_starts_and_stops(self) -> None:
        watchdog = LoopWatchdog(interval_seconds=0.01, threshold_seconds=10.0)
        await watchdog.start()
        assert watchdog.running is True
        await watchdog.stop()
        assert watchdog.running is False

    async def test_starting_twice_runs_one_task(self) -> None:
        watchdog = LoopWatchdog(interval_seconds=0.01, threshold_seconds=10.0)
        await watchdog.start()
        first = watchdog._task
        await watchdog.start()
        try:
            assert watchdog._task is first
        finally:
            await watchdog.stop()

    async def test_stopping_one_that_never_started_is_a_no_op(self) -> None:
        await LoopWatchdog().stop()

    async def test_a_quiet_loop_reports_nothing(self, caplog: pytest.LogCaptureFixture) -> None:
        watchdog = LoopWatchdog(interval_seconds=0.01, threshold_seconds=5.0)
        with caplog.at_level(logging.ERROR):
            await watchdog.start()
            await asyncio.sleep(0.05)
            await watchdog.stop()
        assert "blocked" not in caplog.text

    async def test_a_block_is_reported_with_the_agents_that_had_work(self, caplog: pytest.LogCaptureFixture) -> None:
        """It cannot name the callback -- by the time it runs again, the callback has returned."""
        watchdog = LoopWatchdog(interval_seconds=0.01, threshold_seconds=0.0)
        with IN_FLIGHT.track("orders"), caplog.at_level(logging.ERROR):
            await watchdog.start()
            await asyncio.sleep(0.05)
            await watchdog.stop()
        assert "The event loop was blocked" in caplog.text
        assert "orders" in caplog.text
