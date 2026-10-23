"""`asbs validate` reports what the runtime refuses or warns about at startup, on the runtime's terms.

Each test here pins one disagreement the audit found between the validator and a process started
from the same files: a verdict of "valid" for a project whose production pod would not start, or a
warning the pod logs that the validator never mentioned. The validator reads files only, so every
rule is the runtime's own function wherever one exists (``validate_crontab``, ``parse_bool``,
``layer_settings_document``, ``validate_subject_segment``, Dynaconf's environment layering).
"""

from pathlib import Path

import pytest

from blueprint.agent_generator.cli.commands.validate import (
    IDEMPOTENCY_NOTICE,
    ProcessSettings,
    root_findings,
)

CACHED = "from blueprint.agents.app_builder import AppBuilder\n\nagent = AppBuilder().with_cache()\n"
UNCACHED = "from blueprint.agents.app_builder import AppBuilder\n\nagent = AppBuilder()\n"


@pytest.fixture(autouse=True)
def _no_ambient_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """The validator reads the environment as the process does; a developer's shell must not leak in."""
    for name in ("DYNACONF_APP_ENVIRONMENT", "DYNACONF_NATS_URL", "DYNACONF_EVENT_BUS", "DYNACONF_SCHEDULER_MODE"):
        monkeypatch.delenv(name, raising=False)


def _project(
    tmp_path: Path,
    settings: str,
    *,
    main: str = UNCACHED,
    handler: bool = False,
    scheduler: str | None = None,
    handler_source: str = "# handler\n",
) -> Path:
    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "src" / "main.py").write_text(main, encoding="utf-8")
    (tmp_path / "settings.toml").write_text(settings, encoding="utf-8")
    if handler:
        (tmp_path / "src" / "handlers").mkdir(exist_ok=True)
        (tmp_path / "src" / "handlers" / "order_handler.py").write_text(handler_source, encoding="utf-8")
    if scheduler is not None:
        (tmp_path / "src" / "schedulers").mkdir(exist_ok=True)
        (tmp_path / "src" / "schedulers" / "nightly_scheduler.py").write_text(scheduler, encoding="utf-8")
    return tmp_path


def _findings(project: Path, environment: str | None = None) -> tuple[list[str], list[str], list[str]]:
    return root_findings(project, ProcessSettings.load(project, environment))


def _scheduler(crontab: str) -> str:
    return (
        "from blueprint.agents.io.api.scheduling.scheduler import SchedulerBase\n\n\n"
        "class NightlyScheduler(SchedulerBase):\n"
        "    def __init__(self) -> None:\n"
        f'        super().__init__(crontab="{crontab}")\n\n'
        "    async def tick(self) -> None:\n"
        "        pass\n"
    )


class TestTheTargetEnvironment:
    """Audit 3a: a key in any section counted, so a production pod failed on a 'valid' project."""

    def test_the_default_target_is_production_what_both_dockerfiles_set(self, tmp_path: Path) -> None:
        assert ProcessSettings.load(_project(tmp_path, "[default]\n")).environment == "production"

    def test_a_scheduler_mode_set_only_for_development_is_missing_in_production(self, tmp_path: Path) -> None:
        project = _project(tmp_path, '[development]\nscheduler_mode = "in_process"\n', scheduler=_scheduler("0 * * * *"))

        issues, _, _ = _findings(project)

        assert any("no 'scheduler_mode'" in issue for issue in issues)

    def test_the_same_project_is_valid_for_development(self, tmp_path: Path) -> None:
        project = _project(tmp_path, '[development]\nscheduler_mode = "in_process"\n', scheduler=_scheduler("0 * * * *"))

        issues, _, _ = _findings(project, "development")

        assert not [issue for issue in issues if "scheduler_mode" in issue]

    def test_the_environment_variable_selects_the_section_when_no_option_does(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DYNACONF_APP_ENVIRONMENT", "development")
        project = _project(tmp_path, '[development]\nscheduler_mode = "in_process"\n', scheduler=_scheduler("0 * * * *"))

        assert ProcessSettings.load(project).environment == "development"
        issues, _, _ = _findings(project)
        assert not [issue for issue in issues if "scheduler_mode" in issue]

    def test_a_top_level_key_outside_any_section_is_read_by_nothing(self, tmp_path: Path) -> None:
        """Dynaconf in environment mode loads [default], [<env>] and [global] -- nothing else."""
        settings = ProcessSettings.load(_project(tmp_path, 'idempotency_enabled = true\nenvvar_prefix = "DYNACONF"\n[default]\n'))

        warnings = settings.unread_key_warnings()

        assert len(warnings) == 1
        assert "idempotency_enabled" in warnings[0]
        assert "envvar_prefix" not in warnings[0], "The prefix must be a top-level key; it is read there."
        assert settings.root_view().get("idempotency_enabled") is None

    def test_a_nats_value_in_an_inactive_section_is_not_checked(self, tmp_path: Path) -> None:
        project = _project(tmp_path, "[development]\nnats_handler_timeout = -1\n")

        issues, _, _ = _findings(project)

        assert not [issue for issue in issues if "nats_handler_timeout" in issue]


class TestDeduplication:
    """Audit 5a/5b: dedup without a ttl or a cache failed startup and validated clean."""

    def test_the_notice_names_the_cache(self) -> None:
        assert ".with_cache()" in IDEMPOTENCY_NOTICE

    def test_enabled_without_a_ttl_is_an_issue(self, tmp_path: Path) -> None:
        project = _project(tmp_path, "[default]\nidempotency_enabled = true\n", main=CACHED, handler=True)

        issues, _, _ = _findings(project)

        assert any("'idempotency_ttl' is not set" in issue for issue in issues)

    @pytest.mark.parametrize("ttl", ["0", "-5", '"soon"'])
    def test_a_ttl_the_runtime_refuses_is_an_issue(self, tmp_path: Path, ttl: str) -> None:
        project = _project(tmp_path, f"[default]\nidempotency_enabled = true\nidempotency_ttl = {ttl}\n", main=CACHED, handler=True)

        issues, _, _ = _findings(project)

        assert any("idempotency_ttl" in issue for issue in issues)

    def test_enabled_without_a_cache_is_an_issue(self, tmp_path: Path) -> None:
        project = _project(tmp_path, "[default]\nidempotency_enabled = true\nidempotency_ttl = 60\n", handler=True)

        issues, _, _ = _findings(project)

        assert any(".with_cache()" in issue for issue in issues)

    def test_a_complete_opt_in_is_clean(self, tmp_path: Path) -> None:
        project = _project(tmp_path, "[default]\nidempotency_enabled = true\nidempotency_ttl = 60\n", main=CACHED, handler=True)

        issues, warnings, _ = _findings(project)

        assert issues == []
        assert not [warning for warning in warnings if "deduplicates" in warning]

    def test_a_non_boolean_switch_is_an_issue(self, tmp_path: Path) -> None:
        project = _project(tmp_path, '[default]\nidempotency_enabled = "maybe"\n', main=CACHED, handler=True)

        issues, _, _ = _findings(project)

        assert any("must be a boolean" in issue for issue in issues)

    def test_dedup_without_the_nats_heartbeat_is_warned(self, tmp_path: Path) -> None:
        settings = (
            '[default]\nidempotency_enabled = true\nidempotency_ttl = 60\nevent_bus = "nats"\nnats_heartbeat_enabled = false\n'
            'nats_url = "nats://broker:4222"\napp_name = "demo"\n'
        )
        project = _project(tmp_path, settings, main=CACHED, handler=True)

        _, warnings, _ = _findings(project)

        assert any("'nats_heartbeat_enabled = false'" in warning for warning in warnings)

    def test_dedup_under_dapr_is_warned(self, tmp_path: Path) -> None:
        settings = '[default]\nidempotency_enabled = true\nidempotency_ttl = 60\nevent_bus = "dapr"\n'
        project = _project(tmp_path, settings, main=CACHED, handler=True)

        _, warnings, _ = _findings(project)

        assert any("under Dapr, which has no heartbeat" in warning for warning in warnings)

    def test_dedup_on_a_disk_cache_says_the_claim_holds_in_one_process(self, tmp_path: Path) -> None:
        project = _project(tmp_path, "[default]\nidempotency_enabled = true\nidempotency_ttl = 60\n", main=CACHED, handler=True)

        _, _, notices = _findings(project)

        assert any("within one process" in notice and "redis" in notice for notice in notices)

    def test_dedup_on_redis_has_no_such_notice(self, tmp_path: Path) -> None:
        settings = '[default]\nidempotency_enabled = true\nidempotency_ttl = 60\n[default.cache]\nbackend = "redis"\n'
        project = _project(tmp_path, settings, main=CACHED, handler=True)

        _, _, notices = _findings(project)

        assert not [notice for notice in notices if "within one process" in notice]


class TestSchedulerExpressions:
    """Audit 4a/4c: a crontab or timezone the runtime refuses validated clean."""

    def test_day_seven_is_an_issue_in_either_mode(self, tmp_path: Path) -> None:
        project = _project(tmp_path, '[default]\nscheduler_mode = "in_process"\n', main=CACHED, scheduler=_scheduler("0 0 * * 7"))

        issues, _, _ = _findings(project)

        assert any("names day 7" in issue for issue in issues)

    def test_a_numeric_weekday_in_event_mode_is_an_issue(self, tmp_path: Path) -> None:
        settings = '[default]\nscheduler_mode = "event"\nevent_bus = "nats"\nnats_url = "nats://b:4222"\napp_name = "demo"\n'
        project = _project(tmp_path, settings, scheduler=_scheduler("0 0 * * 1"))

        issues, _, _ = _findings(project)

        assert any("gives the day of the week by number" in issue for issue in issues)

    def test_a_numeric_weekday_in_process_is_fine(self, tmp_path: Path) -> None:
        project = _project(tmp_path, '[default]\nscheduler_mode = "in_process"\n', main=CACHED, scheduler=_scheduler("0 0 * * 1"))

        issues, _, _ = _findings(project)

        assert issues == []

    def test_an_expression_that_is_not_cron_is_an_issue(self, tmp_path: Path) -> None:
        project = _project(tmp_path, '[default]\nscheduler_mode = "in_process"\n', main=CACHED, scheduler=_scheduler("every hour"))

        issues, _, _ = _findings(project)

        assert any("not a valid cron expression" in issue for issue in issues)

    def test_a_timezone_that_is_not_iana_is_an_issue_in_process(self, tmp_path: Path) -> None:
        settings = '[default]\nscheduler_mode = "in_process"\nscheduler_timezone = "Mars/Olympus"\n'
        project = _project(tmp_path, settings, main=CACHED, scheduler=_scheduler("0 * * * *"))

        issues, _, _ = _findings(project)

        assert any("not an IANA timezone name" in issue for issue in issues)

    def test_a_valid_timezone_is_fine(self, tmp_path: Path) -> None:
        settings = '[default]\nscheduler_mode = "in_process"\nscheduler_timezone = "Europe/Berlin"\n'
        project = _project(tmp_path, settings, main=CACHED, scheduler=_scheduler("0 * * * *"))

        issues, _, _ = _findings(project)

        assert issues == []

    def test_in_process_on_a_disk_cache_does_not_promise_one_replica(self, tmp_path: Path) -> None:
        project = _project(tmp_path, '[default]\nscheduler_mode = "in_process"\n', main=CACHED, scheduler=_scheduler("0 * * * *"))

        _, _, notices = _findings(project)

        assert any("within one process" in notice for notice in notices)


class TestTransport:
    """Audit 12a and 15: an unset nats_url outside development, and handlers with no bus."""

    def test_handlers_without_an_event_bus_are_warned(self, tmp_path: Path) -> None:
        project = _project(tmp_path, '[default]\napp_name = "demo"\n', handler=True)

        _, warnings, _ = _findings(project)

        assert any("no valid event_bus" in warning for warning in warnings)

    def test_nats_without_a_url_in_production_is_a_notice(self, tmp_path: Path) -> None:
        """B2 -- an issue failed every image build that validates; the deployment sets it at container start."""
        project = _project(tmp_path, '[default]\napp_name = "demo"\nevent_bus = "nats"\n', handler=True)

        issues, _, notices = _findings(project)

        assert not any("'nats_url' is not set" in issue for issue in issues)
        assert any("'nats_url' is not set" in notice for notice in notices)

    def test_nats_without_a_url_in_development_falls_back(self, tmp_path: Path) -> None:
        project = _project(tmp_path, '[default]\napp_name = "demo"\nevent_bus = "nats"\n', handler=True)

        issues, _, _ = _findings(project, "development")

        assert not [issue for issue in issues if "nats_url" in issue]

    def test_a_url_from_the_environment_counts(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DYNACONF_NATS_URL", "nats://broker:4222")
        project = _project(tmp_path, '[default]\napp_name = "demo"\nevent_bus = "nats"\n', handler=True)

        issues, _, _ = _findings(project)

        assert not [issue for issue in issues if "nats_url" in issue]

    def test_a_non_boolean_heartbeat_is_an_issue(self, tmp_path: Path) -> None:
        settings = '[default]\napp_name = "demo"\nevent_bus = "nats"\nnats_url = "nats://b:4222"\nnats_heartbeat_enabled = "false"\n'
        project = _project(tmp_path, settings, handler=True)

        issues, _, _ = _findings(project)

        assert any("'nats_heartbeat_enabled' must be true or false" in issue for issue in issues)

    def test_an_app_name_that_cannot_be_a_queue_group_is_an_issue(self, tmp_path: Path) -> None:
        settings = '[default]\napp_name = "My Service"\nevent_bus = "nats"\nnats_url = "nats://b:4222"\n'
        project = _project(tmp_path, settings, handler=True)

        issues, _, _ = _findings(project)

        assert any("The queue group (from 'app_name')" in issue for issue in issues)

    def test_one_durable_name_for_several_topics_is_an_issue(self, tmp_path: Path) -> None:
        settings = (
            '[default]\napp_name = "demo"\nevent_bus = "nats"\nnats_url = "nats://b:4222"\nnats_use_jetstream = true\n'
            'nats_durable_name = "orders"\n'
        )
        source = (
            "class OrderHandler:\n    def get_subscribed_topics(self) -> list[str]:\n        return ['orders.created', 'orders.paid']\n"
        )
        project = _project(tmp_path, settings, handler=True, handler_source=source)

        issues, _, _ = _findings(project)

        assert any("'nats_durable_name' is set to 'orders' but 2 topics" in issue for issue in issues)

    def test_an_invalid_loop_debug_value_is_an_issue(self, tmp_path: Path) -> None:
        project = _project(tmp_path, '[default]\nevent_loop_debug = "sometimes"\n')

        issues, _, _ = _findings(project)

        assert any("event_loop_debug" in issue for issue in issues)


class TestTheValidatorAppliesTheRuntimesOwnRules:
    """N19 -- a rule restated in the validator drifts from the runtime's; it calls the runtime's function instead."""

    @pytest.mark.parametrize(
        ("module", "name"),
        [
            ("blueprint.agents.clients.io.nats_client", "resolve_nats_url"),
            ("blueprint.agents.clients.io.nats_client", "resolve_heartbeat_enabled"),
            ("blueprint.agents.clients.io.nats_client", "resolve_root_queue_group"),
            ("blueprint.agents.clients.io.nats_client", "validate_durable_name"),
            ("blueprint.agents.clients.io.nats_client", "resolve_nak_delays"),
            ("blueprint.agents.handler.handler_chain", "resolve_idempotency_policy"),
            ("blueprint.agents.handler.handler_chain", "dedup_redelivery_warning"),
            ("blueprint.agents.io.api.scheduling.scheduler", "resolve_scheduler_timezone"),
        ],
    )
    def test_the_single_command_uses_the_runtimes_function(self, module: str, name: str) -> None:
        import importlib

        from blueprint.agent_generator.cli.commands import validate

        assert getattr(validate, name) is getattr(importlib.import_module(module), name)

    @pytest.mark.parametrize(
        ("module", "name"),
        [
            ("blueprint.agents.io.api.eventing.dapr", "shared_topic_warnings"),
            ("blueprint.agents.group_config", "group_file_path"),
        ],
    )
    def test_the_group_command_uses_the_runtimes_function(self, module: str, name: str) -> None:
        import importlib

        from blueprint.agent_generator.cli.commands import validate_group

        assert getattr(validate_group, name) is getattr(importlib.import_module(module), name)
