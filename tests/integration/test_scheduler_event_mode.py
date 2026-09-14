"""Integration test: an event-mode scheduler is ticked through the ordinary event path.

Offline by design. Under Dapr the application holds no broker connection -- the sidecar
pushes to ``POST /events/{topic}`` -- so the whole of ``scheduler_mode = "event"`` can be
exercised with nothing listening anywhere: build the app, post a CloudEvent to the
scheduler's tick topic, and the scheduler's ``tick()`` runs.

Two claims that unit tests cannot make are pinned here, because both are about what
``build()`` hands to FastAPI:

- ``POST /api/{scheduler_name}/trigger`` is actually served. The route used to be added to
  the scheduler's router during ``on_startup``, which is after ``include_router`` copied it.
- The tick topic reaches the Dapr subscription document, so a sidecar would be told to
  deliver it.
"""

import logging

import pytest
from fastapi.testclient import TestClient

from blueprint.agents.app_builder import AppBuilder
from blueprint.agents.component.component import Component
from blueprint.agents.config import Config
from blueprint.agents.io.api.scheduling import SchedulerBase


class NightlyScheduler(SchedulerBase):
    """Records its ticks so the test can count them."""

    def __init__(self) -> None:
        super().__init__(crontab="0 3 * * *")
        self.ticks = 0

    async def tick(self) -> None:
        self.ticks += 1


@pytest.fixture(autouse=True)
def _reset_component_state():
    Component.reset_shared_state()
    yield
    Component.reset_shared_state()


def _config(tmp_path, mode: str) -> Config:
    settings = tmp_path / "settings.toml"
    settings.write_text(
        "\n".join(
            [
                "[default]",
                'app_name = "cron-test"',
                'event_bus = "dapr"',
                f'scheduler_mode = "{mode}"',
            ]
        )
    )
    return Config(settings_files=[str(settings)])


# Not marked @pytest.mark.integration -- nothing here reaches the network, so these must run
# in the offline CI matrix alongside test_sessions_startup_resilience.py.
def test_event_mode_tick_arrives_as_an_event(tmp_path):
    scheduler = NightlyScheduler()
    app = AppBuilder(_config(tmp_path, "event")).with_scheduler(scheduler).build()

    topic = scheduler.tick_topic
    assert topic == "cron-test.scheduler.nightly_scheduler"

    with TestClient(app) as client:
        # The sidecar would be told to deliver this topic.
        subscriptions = client.get("/dapr/subscribe").json()
        assert {entry["topic"] for entry in subscriptions} == {topic}
        assert [entry["route"] for entry in subscriptions] == [f"/events/{topic}"]

        response = client.post(
            f"/events/{topic}",
            json={
                "id": "tick-1",
                "source": "cronjob/cron-test",
                "type": "cron.tick",
                "specversion": "1.0",
                "data": {},
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "SUCCESS"
    assert scheduler.ticks == 1


def test_event_mode_starts_no_in_process_timer(tmp_path):
    scheduler = NightlyScheduler()
    app = AppBuilder(_config(tmp_path, "event")).with_scheduler(scheduler).build()

    with TestClient(app):
        assert scheduler._scheduler is None

    assert scheduler.ticks == 0


def test_manual_trigger_route_is_served(tmp_path):
    """It was added to the router after include_router had already copied it."""
    scheduler = NightlyScheduler()
    app = AppBuilder(_config(tmp_path, "event")).with_scheduler(scheduler).build()

    with TestClient(app) as client:
        response = client.post(f"/api/{scheduler.name}/trigger")

    assert response.status_code == 200
    assert response.json() == {"status": "triggered", "scheduler": scheduler.name}
    assert scheduler.ticks == 1


def test_in_process_mode_declares_no_tick_topic(tmp_path):
    """No tick handler, so nothing is subscribed and the sidecar is told nothing."""
    scheduler = NightlyScheduler()
    app = AppBuilder(_config(tmp_path, "in_process")).with_scheduler(scheduler).build()

    assert scheduler.tick_handler is None
    assert Component.shared_registry.get_event_handler() == []

    with TestClient(app) as client:
        # No handler was registered, so build() created no eventing endpoint at all.
        assert client.get("/dapr/subscribe").status_code == 404
        assert scheduler._scheduler is not None


def test_a_registered_scheduler_without_a_mode_fails_the_build(tmp_path):
    """scheduler_mode has no default: neither value is safe to inherit silently."""
    settings = tmp_path / "settings.toml"
    settings.write_text('[default]\napp_name = "cron-test"\nevent_bus = "dapr"\n')

    with pytest.raises(ValueError, match="'scheduler_mode' is not set") as excinfo:
        AppBuilder(Config(settings_files=[str(settings)])).with_scheduler(NightlyScheduler()).build()

    assert "event" in str(excinfo.value)
    assert "in_process" in str(excinfo.value)


def test_event_mode_without_a_transport_fails_the_build(tmp_path):
    """Otherwise the scheduler would run forever without ticking, in silence."""
    settings = tmp_path / "settings.toml"
    settings.write_text('[default]\napp_name = "cron-test"\nscheduler_mode = "event"\n')

    with pytest.raises(ValueError, match="'event_bus'"):
        AppBuilder(Config(settings_files=[str(settings)])).with_scheduler(NightlyScheduler()).build()


def test_a_pure_scheduler_can_opt_into_publishing(tmp_path):
    """The scheduler-only shape that wants to emit a result but consume nothing."""
    settings = tmp_path / "settings.toml"
    settings.write_text(
        "\n".join(
            [
                "[default]",
                'app_name = "cron-test"',
                'event_bus = "dapr"',
                'scheduler_mode = "in_process"',
                "event_publishing_enabled = true",
            ]
        )
    )

    app = AppBuilder(Config(settings_files=[str(settings)])).with_scheduler(NightlyScheduler()).build()
    registry = Component.shared_registry

    # A client to publish through, and a publishing service to publish with...
    assert registry.get_io_clients() != []
    assert "event_publishing_service" in [service.name for service in registry.get_services()]
    # ...but nothing that consumes: no handler, no subscription document, no /events route.
    assert registry.get_event_handler() == []
    with TestClient(app) as client:
        assert client.get("/dapr/subscribe").status_code == 404
        assert client.post("/events/anything", json={}).status_code == 404


def test_a_pure_scheduler_publishes_nothing_by_default(tmp_path):
    """Opt-in: a project that only wants a timer may have no broker access at all."""
    app = AppBuilder(_config(tmp_path, "in_process")).with_scheduler(NightlyScheduler()).build()
    registry = Component.shared_registry

    assert registry.get_io_clients() == []
    with TestClient(app):
        pass
    assert "event_publishing_service" not in [service.name for service in registry.get_services()]


def test_a_scheduler_lifecycle_runs_once_per_lifespan(tmp_path, caplog):
    """#43, in-process half: a scheduler is a RestApiBase, so it was in both lifespan loops.

    Before the fix that started two AsyncIOScheduler instances per scheduler in a single
    replica, only one of which on_shutdown could reach.
    """
    scheduler = NightlyScheduler()
    app = AppBuilder(_config(tmp_path, "in_process")).with_scheduler(scheduler).build()

    with caplog.at_level(logging.WARNING):
        with TestClient(app):
            assert scheduler._scheduler is not None

    assert "already started" not in caplog.text
    assert scheduler._scheduler is None
