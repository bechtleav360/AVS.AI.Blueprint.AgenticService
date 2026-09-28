"""Per-agent in-flight accounting, which is what makes an OOM kill attributable (C7)."""

from collections.abc import Iterator

import pytest

from blueprint.agents.io.telemetry.inflight import IN_FLIGHT, InFlightRegister
from blueprint.agents.io.telemetry.providers import reset_providers


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    IN_FLIGHT.reset()
    reset_providers()
    yield
    IN_FLIGHT.reset()
    reset_providers()


@pytest.fixture
def register() -> InFlightRegister:
    return InFlightRegister()


class TestCounting:
    def test_an_agent_starts_at_zero(self, register: InFlightRegister) -> None:
        assert register.count("orders") == 0

    def test_the_count_rises_inside_the_block(self, register: InFlightRegister) -> None:
        with register.track("orders"):
            assert register.count("orders") == 1

    def test_the_count_falls_again(self, register: InFlightRegister) -> None:
        with register.track("orders"):
            pass
        assert register.count("orders") == 0

    def test_a_raising_dispatch_still_decrements(self, register: InFlightRegister) -> None:
        """A leaked count would grow without bound and make the gauge report a stuck agent."""
        with pytest.raises(RuntimeError), register.track("orders"):
            raise RuntimeError("boom")
        assert register.count("orders") == 0

    def test_concurrent_dispatches_are_counted_separately(self, register: InFlightRegister) -> None:
        with register.track("orders"), register.track("orders"):
            assert register.count("orders") == 2

    def test_agents_are_counted_apart(self, register: InFlightRegister) -> None:
        with register.track("orders"):
            assert register.count("billing") == 0

    def test_the_root_is_an_agent_like_any_other(self, register: InFlightRegister) -> None:
        with register.track(""):
            assert register.count("") == 1

    def test_an_agent_stays_listed_after_its_work_finishes(self, register: InFlightRegister) -> None:
        """The watchdog reads this list, and an agent at zero is a fact worth reporting."""
        with register.track("orders"):
            pass
        assert register.namespaces() == ("orders",)
