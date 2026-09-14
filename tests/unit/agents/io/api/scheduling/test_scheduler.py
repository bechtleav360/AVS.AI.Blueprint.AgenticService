"""Unit tests for SchedulerBase and SchedulerTickHandler."""

import logging
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from blueprint.agents.component.component import Component
from blueprint.agents.component.registry import Registry
from blueprint.agents.io.api.scheduling.scheduler import (
    SCHEDULER_MODE_EVENT,
    SCHEDULER_MODE_IN_PROCESS,
    TICK_CACHE_NAMESPACE,
    TICK_CLAIM_TTL_SECONDS,
    SchedulerBase,
    SchedulerTickHandler,
    validate_crontab,
)
from blueprint.agents.component.namespace import namespace_scope
from blueprint.agents.services.infrastructure.cache_service import DiskCacheService

_SCHEDULER_MODULE = "blueprint.agents.io.api.scheduling.scheduler"


class _TestScheduler(SchedulerBase):
    """Minimal concrete scheduler for testing."""

    tick_call_count: int = 0

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(crontab="*/5 * * * *", **kwargs)
        self.tick_call_count = 0

    async def tick(self) -> None:
        self.tick_call_count += 1

    async def on_startup(self) -> None:
        await super().on_startup()

    async def on_shutdown(self) -> None:
        await super().on_shutdown()


class _FailingScheduler(SchedulerBase):
    """Scheduler whose tick always fails, for the transport-edge contract."""

    def __init__(self) -> None:
        super().__init__(crontab="*/5 * * * *")

    async def tick(self) -> None:
        raise RuntimeError("tick exploded")


@pytest.fixture
def settings(mock_config: MagicMock) -> dict[str, Any]:
    """Back ``config.get`` with a mutable dict so a test can set its own keys.

    ``scheduler_mode`` is deliberately absent: it has no default, so every test that needs
    a mode states it, exactly as a project must.
    """
    values: dict[str, Any] = {"app_name": "cleanup_service", "event_bus": "nats"}
    mock_config.get.side_effect = lambda key, default=None: values.get(key, default)
    return values


@pytest.fixture
def scheduler(settings: dict[str, Any], mock_registry: MagicMock) -> _TestScheduler:
    """Return a concrete SchedulerBase instance in event mode."""
    settings["scheduler_mode"] = SCHEDULER_MODE_EVENT
    return _TestScheduler()


@pytest.fixture
def in_process_scheduler(settings: dict[str, Any], mock_registry: MagicMock) -> _TestScheduler:
    """Return a concrete SchedulerBase instance with the in-process timer selected."""
    settings["scheduler_mode"] = SCHEDULER_MODE_IN_PROCESS
    return _TestScheduler()


class TestTriggerTick:
    async def test_trigger_tick_calls_tick(self, scheduler: _TestScheduler) -> None:
        await scheduler._trigger_tick()
        assert scheduler.tick_call_count == 1

    async def test_trigger_tick_returns_triggered_status(self, scheduler: _TestScheduler) -> None:
        result = await scheduler._trigger_tick()
        assert result["status"] == "triggered"

    async def test_trigger_tick_returns_scheduler_name(self, scheduler: _TestScheduler) -> None:
        result = await scheduler._trigger_tick()
        assert result["scheduler"] == scheduler.name

    async def test_trigger_tick_calls_tick_once_per_call(self, scheduler: _TestScheduler) -> None:
        await scheduler._trigger_tick()
        await scheduler._trigger_tick()
        assert scheduler.tick_call_count == 2


class TestSchedulerMode:
    def test_mode_reads_event(self, scheduler: _TestScheduler) -> None:
        assert scheduler.scheduler_mode == SCHEDULER_MODE_EVENT

    def test_mode_reads_in_process(self, in_process_scheduler: _TestScheduler) -> None:
        assert in_process_scheduler.scheduler_mode == SCHEDULER_MODE_IN_PROCESS

    def test_mode_tolerates_case_and_whitespace(self, settings: dict[str, Any], scheduler: _TestScheduler) -> None:
        settings["scheduler_mode"] = "  IN_PROCESS  "
        assert scheduler.scheduler_mode == SCHEDULER_MODE_IN_PROCESS

    @pytest.mark.parametrize("absent", [None, "", "   "])
    def test_absent_mode_raises_naming_both_values(self, absent: str | None, settings: dict[str, Any], scheduler: _TestScheduler) -> None:
        """The key has no default -- neither value is safe to inherit silently."""
        settings["scheduler_mode"] = absent
        with pytest.raises(ValueError, match="'scheduler_mode' is not set") as excinfo:
            _ = scheduler.scheduler_mode
        message = str(excinfo.value)
        assert SCHEDULER_MODE_EVENT in message
        assert SCHEDULER_MODE_IN_PROCESS in message

    def test_missing_mode_key_raises(self, settings: dict[str, Any], mock_registry: MagicMock) -> None:
        settings.pop("scheduler_mode", None)
        with pytest.raises(ValueError, match="'scheduler_mode' is not set"):
            _ = _TestScheduler().scheduler_mode

    def test_unknown_mode_raises(self, settings: dict[str, Any], scheduler: _TestScheduler) -> None:
        settings["scheduler_mode"] = "leader_election"
        with pytest.raises(ValueError, match="scheduler_mode"):
            _ = scheduler.scheduler_mode

    def test_mode_is_resolved_once(self, settings: dict[str, Any], scheduler: _TestScheduler) -> None:
        assert scheduler.scheduler_mode == SCHEDULER_MODE_EVENT
        settings["scheduler_mode"] = SCHEDULER_MODE_IN_PROCESS
        assert scheduler.scheduler_mode == SCHEDULER_MODE_EVENT


class TestValidateCrontab:
    """Event mode parses the crontab nowhere else, so a typo has to fail here."""

    @pytest.mark.parametrize("crontab", ["0 3 * * *", "*/15 * * * *", "0 0 1 * 1"])
    def test_accepts_the_five_standard_fields(self, crontab: str) -> None:
        assert validate_crontab(crontab) == crontab

    def test_strips_surrounding_whitespace(self) -> None:
        assert validate_crontab("  0 3 * * *  ") == "0 3 * * *"

    @pytest.mark.parametrize("crontab", ["", "   "])
    def test_empty_raises(self, crontab: str) -> None:
        with pytest.raises(ValueError, match="empty"):
            validate_crontab(crontab)

    def test_nonsense_raises(self) -> None:
        with pytest.raises(ValueError, match="not a valid cron expression"):
            validate_crontab("every tuesday")

    def test_a_six_field_expression_raises(self) -> None:
        """A leading seconds field is an apscheduler extension no cron reads."""
        with pytest.raises(ValueError, match="five standard"):
            validate_crontab("0 0 3 * * *")

    def test_event_mode_wiring_rejects_a_bad_crontab(self, settings: dict[str, Any], mock_registry: MagicMock) -> None:
        settings["scheduler_mode"] = SCHEDULER_MODE_EVENT

        class _BadCrontabScheduler(SchedulerBase):
            def __init__(self) -> None:
                super().__init__(crontab="0 3 * *")

            async def tick(self) -> None:
                """Never called."""

        with pytest.raises(ValueError, match="cron"):
            _BadCrontabScheduler().wire()

    def test_in_process_wiring_does_not_reach_the_check(self, settings: dict[str, Any], mock_registry: MagicMock) -> None:
        """apscheduler validates it there, at the point it builds the trigger."""
        settings["scheduler_mode"] = SCHEDULER_MODE_IN_PROCESS

        class _LooseCrontabScheduler(SchedulerBase):
            def __init__(self) -> None:
                super().__init__(crontab="0 3 * *")

            async def tick(self) -> None:
                """Never called."""

        assert _LooseCrontabScheduler().wire() is None


class TestTickTopic:
    def test_topic_derives_from_app_name_when_no_name_was_given(self, scheduler: _TestScheduler) -> None:
        """No namespace, so app_name is the identity -- which is every single-agent application."""
        assert scheduler.tick_topic == f"cleanup_service.scheduler.{scheduler.name}"

    def test_a_namespaced_scheduler_derives_from_its_own_name(self, settings: dict[str, Any], mock_registry: MagicMock) -> None:
        """The name given in code wins over app_name, which belongs to the whole process.

        This read used to be the module constant ROOT_NAMESPACE -- always "" -- left as a
        placeholder for phase 2, so a namespaced scheduler derived its subject from app_name.
        """
        settings["scheduler_mode"] = SCHEDULER_MODE_EVENT
        with namespace_scope("orders"):
            namespaced = _TestScheduler()

        assert namespaced.tick_topic == f"orders.scheduler.{namespaced.name}"

    def test_two_agents_schedulers_of_one_name_get_two_subjects(self, settings: dict[str, Any], mock_registry: MagicMock) -> None:
        """Derived from app_name they shared a subject and consumed each other's ticks."""
        settings["scheduler_mode"] = SCHEDULER_MODE_EVENT
        with namespace_scope("orders"):
            orders = _TestScheduler()
        with namespace_scope("billing"):
            billing = _TestScheduler()

        assert orders.tick_topic != billing.tick_topic
        assert orders.tick_topic.startswith("orders.") and billing.tick_topic.startswith("billing.")

    def test_topic_follows_a_renamed_scheduler(self, settings: dict[str, Any], mock_registry: MagicMock) -> None:
        renamed = _TestScheduler()
        renamed.name = "nightly"
        assert renamed.tick_topic == "cleanup_service.scheduler.nightly"

    def test_explicit_topic_overrides_the_derived_one(self, settings: dict[str, Any], mock_registry: MagicMock) -> None:
        overridden = _TestScheduler(topic="ops.cron.nightly")
        assert overridden.tick_topic == "ops.cron.nightly"

    def test_missing_identity_raises(self, settings: dict[str, Any], scheduler: _TestScheduler) -> None:
        settings["app_name"] = ""
        with pytest.raises(ValueError, match="tick topic cannot be derived"):
            _ = scheduler.tick_topic

    @pytest.mark.parametrize("topic", ["ops.cron.*", "ops.cron.>"])
    def test_wildcard_topic_raises(self, topic: str, settings: dict[str, Any], mock_registry: MagicMock) -> None:
        unusable = _TestScheduler(topic=topic)
        with pytest.raises(ValueError, match="cannot appear in a NATS subject"):
            _ = unusable.tick_topic

    def test_whitespace_in_an_explicit_topic_raises(self, settings: dict[str, Any], mock_registry: MagicMock) -> None:
        unusable = _TestScheduler(topic="ops cron nightly")
        with pytest.raises(ValueError, match="cannot appear in a NATS subject"):
            _ = unusable.tick_topic

    def test_whitespace_in_the_identity_is_rejected_not_rewritten(self, settings: dict[str, Any], mock_registry: MagicMock) -> None:
        """A CronJob is written against this subject by someone who cannot see the rewrite."""
        settings["app_name"] = "Health Monitor"
        derived = _TestScheduler()
        with pytest.raises(ValueError, match="cannot appear in a NATS subject"):
            _ = derived.tick_topic

    def test_the_identity_error_names_the_key_and_the_subject_it_would_have_made(
        self, settings: dict[str, Any], mock_registry: MagicMock
    ) -> None:
        settings["app_name"] = "Health Monitor"
        derived = _TestScheduler()
        with pytest.raises(ValueError, match="'app_name'.*'Health Monitor'.*Health Monitor.scheduler"):
            _ = derived.tick_topic

    def test_wildcard_in_the_identity_is_rejected(self, settings: dict[str, Any], mock_registry: MagicMock) -> None:
        settings["app_name"] = "health*monitor"
        derived = _TestScheduler()
        with pytest.raises(ValueError, match="cannot appear in a NATS subject"):
            _ = derived.tick_topic

    def test_whitespace_in_the_scheduler_name_is_rejected(self, settings: dict[str, Any], mock_registry: MagicMock) -> None:
        """with_scheduler(name=...) reaches the subject too, so it is checked as well."""
        renamed = _TestScheduler()
        renamed.name = "night ly"
        with pytest.raises(ValueError, match="cannot appear in a NATS subject"):
            _ = renamed.tick_topic


class TestWire:
    def test_event_mode_creates_a_tick_handler_on_the_tick_topic(self, scheduler: _TestScheduler) -> None:
        handler = scheduler.wire()
        assert isinstance(handler, SchedulerTickHandler)
        assert handler.topic == scheduler.tick_topic
        assert handler.scheduler is scheduler
        assert scheduler.tick_handler is handler

    def test_in_process_mode_creates_no_tick_handler(self, in_process_scheduler: _TestScheduler) -> None:
        assert in_process_scheduler.wire() is None
        assert in_process_scheduler.tick_handler is None

    def test_wire_is_idempotent(self, scheduler: _TestScheduler) -> None:
        first = scheduler.wire()
        second = scheduler.wire()
        assert first is second

    def test_wire_registers_the_trigger_route(self, scheduler: _TestScheduler) -> None:
        scheduler.wire()
        paths = [route.path for route in scheduler.router.routes if hasattr(route, "path")]
        assert paths == [f"/{scheduler.name}/trigger"]

    def test_wire_registers_the_trigger_route_once(self, scheduler: _TestScheduler) -> None:
        scheduler.wire()
        scheduler.wire()
        paths = [route.path for route in scheduler.router.routes if hasattr(route, "path")]
        assert paths == [f"/{scheduler.name}/trigger"]

    def test_in_process_mode_still_registers_the_trigger_route(self, in_process_scheduler: _TestScheduler) -> None:
        in_process_scheduler.wire()
        paths = [route.path for route in in_process_scheduler.router.routes if hasattr(route, "path")]
        assert paths == [f"/{in_process_scheduler.name}/trigger"]

    @pytest.mark.parametrize("bus", [None, "", "sessions"])
    def test_event_mode_without_a_usable_transport_raises(
        self, bus: str | None, settings: dict[str, Any], mock_registry: MagicMock
    ) -> None:
        """Event mode with nothing to subscribe to would run forever without ticking."""
        settings["event_bus"] = bus
        settings["scheduler_mode"] = SCHEDULER_MODE_EVENT
        with pytest.raises(ValueError, match="'event_bus'"):
            _TestScheduler().wire()

    @pytest.mark.parametrize("bus", ["dapr", "NATS"])
    def test_event_mode_accepts_either_broker_transport(self, bus: str, settings: dict[str, Any], mock_registry: MagicMock) -> None:
        settings["event_bus"] = bus
        settings["scheduler_mode"] = SCHEDULER_MODE_EVENT
        assert _TestScheduler().wire() is not None

    def test_in_process_mode_needs_no_transport(self, settings: dict[str, Any], mock_registry: MagicMock) -> None:
        settings["event_bus"] = ""
        settings["scheduler_mode"] = SCHEDULER_MODE_IN_PROCESS
        assert _TestScheduler().wire() is None


class TestSchedulerOnStartup:
    async def test_event_mode_starts_no_timer(self, scheduler: _TestScheduler) -> None:
        with patch("blueprint.agents.io.api.scheduling.scheduler.AsyncIOScheduler") as mock_sched_cls:
            await scheduler.on_startup()
        mock_sched_cls.assert_not_called()
        assert scheduler._scheduler is None

    async def test_event_mode_wires_the_tick_handler(self, scheduler: _TestScheduler) -> None:
        await scheduler.on_startup()
        assert scheduler.tick_handler is not None

    async def test_in_process_mode_creates_apscheduler(self, in_process_scheduler: _TestScheduler) -> None:
        with patch("blueprint.agents.io.api.scheduling.scheduler.AsyncIOScheduler") as mock_sched_cls:
            mock_sched = MagicMock()
            mock_sched_cls.return_value = mock_sched
            await in_process_scheduler.on_startup()
        mock_sched_cls.assert_called_once()
        mock_sched.start.assert_called_once()
        assert in_process_scheduler._scheduler is mock_sched

    async def test_in_process_mode_schedules_the_tick_on_the_crontab(self, in_process_scheduler: _TestScheduler) -> None:
        with patch("blueprint.agents.io.api.scheduling.scheduler.AsyncIOScheduler") as mock_sched_cls:
            mock_sched = MagicMock()
            mock_sched_cls.return_value = mock_sched
            await in_process_scheduler.on_startup()
        job_args, job_kwargs = mock_sched.add_job.call_args
        assert job_args[0] == in_process_scheduler._claimed_tick
        assert job_kwargs["name"] == in_process_scheduler.name

    async def test_on_startup_registers_trigger_endpoint(self, scheduler: _TestScheduler) -> None:
        await scheduler.on_startup()
        paths = [route.path for route in scheduler.router.routes if hasattr(route, "path")]
        assert paths == [f"/{scheduler.name}/trigger"]

    async def test_repeated_startup_starts_no_second_timer(self, in_process_scheduler: _TestScheduler) -> None:
        """#43: two build() passes drive the lifespan twice over the same registry."""
        with patch("blueprint.agents.io.api.scheduling.scheduler.AsyncIOScheduler") as mock_sched_cls:
            mock_sched_cls.return_value = MagicMock()
            await in_process_scheduler.on_startup()
            await in_process_scheduler.on_startup()
        mock_sched_cls.assert_called_once()

    async def test_repeated_startup_adds_no_second_route(self, scheduler: _TestScheduler) -> None:
        await scheduler.on_startup()
        await scheduler.on_startup()
        paths = [route.path for route in scheduler.router.routes if hasattr(route, "path")]
        assert paths == [f"/{scheduler.name}/trigger"]


class TestSchedulerOnShutdown:
    async def test_on_shutdown_calls_scheduler_shutdown(self, scheduler: _TestScheduler) -> None:
        mock_sched = MagicMock()
        mock_sched.running = True
        scheduler._scheduler = mock_sched
        await scheduler.on_shutdown()
        mock_sched.shutdown.assert_called_once_with(wait=True)

    async def test_on_shutdown_is_safe_when_scheduler_none(self, scheduler: _TestScheduler) -> None:
        scheduler._scheduler = None
        await scheduler.on_shutdown()  # must not raise

    async def test_on_shutdown_skips_shutdown_when_not_running(self, scheduler: _TestScheduler) -> None:
        mock_sched = MagicMock()
        mock_sched.running = False
        scheduler._scheduler = mock_sched
        await scheduler.on_shutdown()
        mock_sched.shutdown.assert_not_called()

    async def test_shutdown_allows_a_later_restart(self, in_process_scheduler: _TestScheduler) -> None:
        with patch("blueprint.agents.io.api.scheduling.scheduler.AsyncIOScheduler") as mock_sched_cls:
            mock_sched_cls.return_value = MagicMock()
            await in_process_scheduler.on_startup()
            await in_process_scheduler.on_shutdown()
            await in_process_scheduler.on_startup()
        assert mock_sched_cls.call_count == 2


class TestSchedulerTickHandler:
    @pytest.fixture
    def handler(self, scheduler: _TestScheduler) -> SchedulerTickHandler:
        wired = scheduler.wire()
        assert wired is not None
        return wired

    def test_declares_the_tick_topic(self, handler: SchedulerTickHandler, scheduler: _TestScheduler) -> None:
        assert handler.get_subscribed_topics() == [scheduler.tick_topic]

    def test_runs_ahead_of_the_default_handler_priority(self, handler: SchedulerTickHandler) -> None:
        assert handler._priority < 100

    def test_is_named_after_its_scheduler(self, handler: SchedulerTickHandler, scheduler: _TestScheduler) -> None:
        assert handler.name == f"{scheduler.name}_tick"

    @pytest.mark.parametrize("context_key", ["nats_topic", "dapr_topic", "topic"])
    async def test_claims_a_delivery_on_its_own_topic(
        self, context_key: str, handler: SchedulerTickHandler, scheduler: _TestScheduler
    ) -> None:
        assert await handler.can_handle_event(MagicMock(), {context_key: scheduler.tick_topic}) is True

    async def test_declines_another_topic(self, handler: SchedulerTickHandler) -> None:
        assert await handler.can_handle_event(MagicMock(), {"nats_topic": "orders.created"}) is False

    async def test_declines_a_delivery_with_no_topic(self, handler: SchedulerTickHandler) -> None:
        assert await handler.can_handle_event(MagicMock(), {}) is False

    async def test_handle_event_ticks_the_scheduler(self, handler: SchedulerTickHandler, scheduler: _TestScheduler) -> None:
        result = await handler.handle_event(MagicMock(), {})
        assert scheduler.tick_call_count == 1
        assert result == {"status": "ticked", "scheduler": scheduler.name}

    async def test_handle_event_returns_no_event_to_publish(self, handler: SchedulerTickHandler) -> None:
        """A plain dict stops the chain without publishing anything downstream."""
        result = await handler.handle_event(MagicMock(), {})
        assert "event_type" not in result

    async def test_a_failing_tick_reaches_the_transport_edge(self, settings: dict[str, Any], mock_registry: MagicMock) -> None:
        settings["scheduler_mode"] = SCHEDULER_MODE_EVENT
        failing = _FailingScheduler()
        handler = failing.wire()
        assert handler is not None
        with pytest.raises(RuntimeError, match="tick exploded"):
            await handler.handle_event(MagicMock(), {})


class TestTickHandlerRegistration:
    """Registration against a real Registry, where a name clash actually raises."""

    def test_two_schedulers_register_distinct_tick_handlers(self, settings: dict[str, Any]) -> None:
        settings["scheduler_mode"] = SCHEDULER_MODE_EVENT
        Component.shared_registry = Registry(Component)

        class _FirstScheduler(_TestScheduler):
            pass

        class _SecondScheduler(_TestScheduler):
            pass

        first = _FirstScheduler().wire()
        second = _SecondScheduler().wire()

        assert first is not None and second is not None
        assert first.name != second.name
        registered = Component.shared_registry.get_event_handler()
        assert sorted(handler.name for handler in registered) == sorted([first.name, second.name])


class TestClaimedTick:
    """#73: every replica's timer fires, and the cache decides which one runs the tick."""

    @pytest.fixture
    def cached_scheduler(self, settings: dict[str, Any], mock_registry: MagicMock) -> _TestScheduler:
        settings["scheduler_mode"] = SCHEDULER_MODE_IN_PROCESS
        mock_registry.has_cache.return_value = True
        return _TestScheduler()

    async def test_the_winner_ticks(self, cached_scheduler: _TestScheduler, mock_registry: MagicMock) -> None:
        mock_registry.cache_service.claim.return_value = True
        await cached_scheduler._claimed_tick()
        assert cached_scheduler.tick_call_count == 1

    async def test_a_loser_does_not_tick(self, cached_scheduler: _TestScheduler, mock_registry: MagicMock) -> None:
        mock_registry.cache_service.claim.return_value = False
        await cached_scheduler._claimed_tick()
        assert cached_scheduler.tick_call_count == 0

    async def test_the_claim_is_keyed_on_the_scheduler_and_the_minute(
        self, cached_scheduler: _TestScheduler, mock_registry: MagicMock
    ) -> None:
        mock_registry.cache_service.claim.return_value = True
        await cached_scheduler._claimed_tick()

        key = mock_registry.cache_service.claim.call_args[0][0]
        assert key["scheduler"] == cached_scheduler.name
        # Minute precision: cron granularity, so replicas firing for one slot agree on it.
        assert len(key["slot"]) == len("2026-09-04T03:00")

    async def test_the_claim_carries_a_ttl_and_its_own_namespace(self, cached_scheduler: _TestScheduler, mock_registry: MagicMock) -> None:
        mock_registry.cache_service.claim.return_value = True
        await cached_scheduler._claimed_tick()

        kwargs = mock_registry.cache_service.claim.call_args.kwargs
        assert kwargs["namespace"] == TICK_CACHE_NAMESPACE
        assert kwargs["ttl"] == TICK_CLAIM_TTL_SECONDS

    async def test_three_replicas_run_one_tick(self, settings: dict[str, Any], tmp_path: Path) -> None:
        """The acceptance criterion, against a real cache shared by three schedulers."""
        settings["scheduler_mode"] = SCHEDULER_MODE_IN_PROCESS
        Component.shared_registry = Registry(Component)
        cache = DiskCacheService(cache_dir=str(tmp_path / "cache"))
        Component.shared_registry.cache_service = cache
        try:
            replicas = []
            for index in range(3):
                replica = _TestScheduler()
                # Three processes are simulated inside one registry, so each instance needs a
                # distinct registry key -- while all three answer to the one agent name the
                # slot key is derived from, which is the point of the test.
                replica.name = f"replica-{index}"
                replica._name = "nightly_scheduler"
                replicas.append(replica)

            for replica in replicas:
                await replica._claimed_tick()

            assert sum(replica.tick_call_count for replica in replicas) == 1
        finally:
            cache.close()

    async def test_a_later_slot_is_claimable_again(self, settings: dict[str, Any], tmp_path: Path) -> None:
        """The key carries the minute, so the next scheduled tick is a fresh claim."""
        settings["scheduler_mode"] = SCHEDULER_MODE_IN_PROCESS
        Component.shared_registry = Registry(Component)
        cache = DiskCacheService(cache_dir=str(tmp_path / "cache"))
        Component.shared_registry.cache_service = cache
        try:
            scheduler = _TestScheduler()
            with patch(f"{_SCHEDULER_MODULE}.datetime") as clock:
                clock.now.return_value.strftime.return_value = "2026-09-04T03:00"
                await scheduler._claimed_tick()
                await scheduler._claimed_tick()
                clock.now.return_value.strftime.return_value = "2026-09-04T04:00"
                await scheduler._claimed_tick()
            assert scheduler.tick_call_count == 2
        finally:
            cache.close()

    async def test_without_a_cache_every_replica_ticks(self, in_process_scheduler: _TestScheduler, mock_registry: MagicMock) -> None:
        """Nothing to claim with, so the mode behaves as it did before -- and startup warns."""
        mock_registry.has_cache.return_value = False
        await in_process_scheduler._claimed_tick()
        assert in_process_scheduler.tick_call_count == 1
        mock_registry.cache_service.claim.assert_not_called()

    async def test_the_timer_runs_the_claimed_tick_not_the_raw_one(self, cached_scheduler: _TestScheduler) -> None:
        with patch("blueprint.agents.io.api.scheduling.scheduler.AsyncIOScheduler") as mock_sched_cls:
            mock_sched = MagicMock()
            mock_sched_cls.return_value = mock_sched
            await cached_scheduler.on_startup()

        assert mock_sched.add_job.call_args[0][0] == cached_scheduler._claimed_tick

    async def test_startup_warns_when_ticks_cannot_be_coordinated(
        self, in_process_scheduler: _TestScheduler, mock_registry: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        mock_registry.has_cache.return_value = False
        with patch("blueprint.agents.io.api.scheduling.scheduler.AsyncIOScheduler"):
            with caplog.at_level(logging.WARNING):
                await in_process_scheduler.on_startup()

        assert "every replica of this process will run every tick" in caplog.text

    async def test_event_mode_does_not_claim(self, scheduler: _TestScheduler, mock_registry: MagicMock) -> None:
        """In event mode the queue group already picks one replica; a claim would be redundant."""
        mock_registry.has_cache.return_value = True
        handler = scheduler.wire()
        assert handler is not None
        await handler.handle_event(MagicMock(), {})

        assert scheduler.tick_call_count == 1
        mock_registry.cache_service.claim.assert_not_called()
