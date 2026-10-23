"""`asbs validate`'s group gates -- what a project must state before it can be grouped.

The gates exist because there is no `asbs migrate`: `main.py` is the developer's own declaration,
and a tool that rewrites it either guesses at intent or fails on anything hand-edited. A checklist
plus a validate that names what is missing is the honest shape, so what these tests hold is that
each thing it can name, it does.

A project holding an `agents.toml` with entries is an image, and is checked by the rules the group
entry point applies (audit 3f): every entry needs a `root`, and an agent's settings are read from
beside its root's `src` -- never from beside the declaration module.
"""

from pathlib import Path

import pytest

from blueprint.agent_generator.cli.commands.validate import NO_AGENT_MAP_NOTICE, ProcessSettings, _group_findings, root_findings

DECLARATION = "from blueprint.agents.app_builder import AppBuilder\n\nagent = AppBuilder()\n"


@pytest.fixture(autouse=True)
def _no_ambient_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("DYNACONF_APP_ENVIRONMENT", "DYNACONF_SCHEDULER_MODE", "DYNACONF_EVENT_BUS", "BLUEPRINT_AGENTS", "BLUEPRINT_GROUP"):
        monkeypatch.delenv(name, raising=False)


def _project(tmp_path: Path, *, agent_map: str | None = None, settings: str | None = None, main: str | None = DECLARATION) -> Path:
    """Build the smallest project shape the group gates look at."""
    if main is not None:
        (tmp_path / "src").mkdir(exist_ok=True)
        (tmp_path / "src" / "main.py").write_text(main, encoding="utf-8")
    if agent_map is not None:
        (tmp_path / "agents.toml").write_text(agent_map, encoding="utf-8")
    if settings is not None:
        (tmp_path / "settings.toml").write_text(settings, encoding="utf-8")
    return tmp_path


def _agent_dir(project: Path, name: str, settings: str = '[default]\nmodel_name = "x"\n') -> Path:
    root = project / "agents" / name
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / "main.py").write_text(DECLARATION, encoding="utf-8")
    (root / "settings.toml").write_text(settings, encoding="utf-8")
    return root


def _agent(name: str = "orders", module: str | None = None, root: str | None = None) -> str:
    module = module if module is not None else f"agents.{name}.src.main:agent"
    root = root if root is not None else f"agents/{name}"
    return f'[agents.{name}]\nroot = "{root}"\nmodule = "{module}"\n'


class TestTheAgentMap:
    """The map is how a name reaches code; the gate is everything that stops it."""

    def test_an_agent_without_one_is_not_told_to_add_one(self, tmp_path: Path) -> None:
        """An agent carries no map by design; it used to be warned and told to add one here."""
        issues, warnings, notices = _group_findings(_project(tmp_path))

        assert not issues, "A project deployed on its own is not broken, so this is never an issue."
        assert warnings == []
        assert notices == [NO_AGENT_MAP_NOTICE]
        assert "belongs to the image" in notices[0]
        assert "asbs validate --group" in notices[0]

    def test_a_well_formed_map_passes_silently(self, tmp_path: Path) -> None:
        project = _project(tmp_path, agent_map=_agent())
        _agent_dir(project, "orders")

        issues, warnings, _ = _group_findings(project)

        assert (issues, warnings) == ([], [])

    def test_an_unparseable_map_is_reported(self, tmp_path: Path) -> None:
        issues, _, _ = _group_findings(_project(tmp_path, agent_map="[agents.orders\nbroken\n"))

        assert len(issues) == 1
        assert "could not be read" in issues[0]

    def test_a_map_with_no_agents_is_reported(self, tmp_path: Path) -> None:
        issues, _, _ = _group_findings(_project(tmp_path, agent_map="# nothing\n"))

        assert "declares no [agents.<name>] entries" in issues[0]

    def test_an_entry_without_a_root_is_reported(self, tmp_path: Path) -> None:
        """Audit 3f: the runtime requires it, and this did not."""
        project = _project(tmp_path, agent_map='[agents.orders]\nmodule = "agents.orders.src.main:agent"\n')
        _agent_dir(project, "orders")

        issues, _, _ = _group_findings(project)

        assert any("has no 'root'" in issue for issue in issues)

    def test_an_entry_without_a_module_is_reported(self, tmp_path: Path) -> None:
        project = _project(tmp_path, agent_map='[agents.orders]\nroot = "agents/orders"\ncritical = true\n')
        _agent_dir(project, "orders")

        issues, _, _ = _group_findings(project)

        assert "has no usable 'module'" in issues[0]

    def test_a_module_that_names_no_attribute_is_reported(self, tmp_path: Path) -> None:
        project = _project(tmp_path, agent_map=_agent(module="agents.orders.src.main"))
        _agent_dir(project, "orders")

        issues, _, _ = _group_findings(project)

        assert "has no usable 'module'" in issues[0]

    def test_a_name_that_cannot_be_a_namespace_is_reported(self, tmp_path: Path) -> None:
        """It becomes a queue group, a durable, a cache partition and a service.name."""
        issues, _, _ = _group_findings(_project(tmp_path, agent_map='[agents.order-eu]\nroot = "x"\nmodule = "x.src.main:agent"\n'))

        assert "cannot be a namespace" in issues[0]

    def test_a_module_that_is_not_in_the_image_is_reported(self, tmp_path: Path) -> None:
        project = _project(tmp_path, agent_map=_agent(module="agents.orders.src.nowhere:agent"))
        _agent_dir(project, "orders")

        issues, _, _ = _group_findings(project)

        assert "is not a module in this image" in issues[0]

    def test_a_module_that_declares_no_such_attribute_is_reported(self, tmp_path: Path) -> None:
        """The attribute is the AppBuilder the host builds; without it the process never starts."""
        project = _project(tmp_path, agent_map=_agent(module="agents.orders.src.main:registration"))
        _agent_dir(project, "orders")

        issues, _, _ = _group_findings(project)

        assert "assigns no 'registration'" in issues[0]

    def test_a_package_declaration_resolves_too(self, tmp_path: Path) -> None:
        project = _project(tmp_path, agent_map=_agent(module="agents.orders.src:agent"))
        root = _agent_dir(project, "orders")
        (root / "src" / "__init__.py").write_text(DECLARATION, encoding="utf-8")

        issues, _, _ = _group_findings(project)

        assert issues == []


class TestSettingsThatWillNotSurviveGrouping:
    """An agent's settings are read from beside its root's src, and scoped to it."""

    def test_settings_beside_the_declaration_are_refused(self, tmp_path: Path) -> None:
        """Audit 3f: they used to be looked for next to the declaration, under src/ -- where the runtime refuses them."""
        project = _project(tmp_path, agent_map=_agent())
        root = _agent_dir(project, "orders")
        (root / "settings.toml").unlink()
        (root / "src" / "settings.toml").write_text('[default]\nmodel_name = "x"\n', encoding="utf-8")

        issues, _, _ = _group_findings(project)

        assert any("'settings.toml'" in issue and "not where it is read from" in issue for issue in issues)

    def test_a_process_scope_key_in_an_agents_settings_is_named(self, tmp_path: Path) -> None:
        """One process binds one port and speaks one bus, so these are dropped at startup."""
        project = _project(tmp_path, agent_map=_agent() + _agent("billing"))
        _agent_dir(project, "orders", '[default]\napp_port = 8000\nevent_bus = "nats"\nmodel_name = "x"\n')
        _agent_dir(project, "billing", '[default]\nmodel_name = "y"\n')

        _, warnings, _ = _group_findings(project)

        orders = next(warning for warning in warnings if "'orders'" in warning)
        assert "app_port, event_bus" in orders
        assert "model_name" not in orders, "A scoped model name is the point of scoping, not a fault."
        assert not [warning for warning in warnings if "'billing'" in warning]


class TestSchedulers:
    """The mode has no default, and one of the two modes fails nowhere at all."""

    def _with_scheduler(self, project: Path) -> Path:
        schedulers = project / "src" / "schedulers"
        schedulers.mkdir(parents=True, exist_ok=True)
        (schedulers / "__init__.py").write_text("", encoding="utf-8")
        (schedulers / "cleanup_scheduler.py").write_text("# scheduler", encoding="utf-8")
        return project

    @staticmethod
    def _findings(project: Path) -> tuple[list[str], list[str], list[str]]:
        return root_findings(project, ProcessSettings.load(project))

    def test_a_project_with_no_schedulers_is_asked_nothing(self, tmp_path: Path) -> None:
        issues, _, notices = self._findings(_project(tmp_path, settings="[default]\n"))

        assert (issues, notices) == ([], [])

    def test_a_scheduler_without_a_mode_is_an_issue(self, tmp_path: Path) -> None:
        """It has no default because neither value is safe to inherit, so build() fails."""
        project = self._with_scheduler(_project(tmp_path, settings='[default]\napp_name = "demo"\n'))

        issues, _, _ = self._findings(project)

        assert "no 'scheduler_mode'" in issues[0]

    def test_an_unknown_mode_is_an_issue(self, tmp_path: Path) -> None:
        project = self._with_scheduler(_project(tmp_path, settings='[default]\nscheduler_mode = "cron"\n'))

        issues, _, _ = self._findings(project)

        assert "must be one of" in issues[0]

    def test_event_mode_says_that_nothing_here_publishes_the_tick(self, tmp_path: Path) -> None:
        """The silent-failure case: a scheduler waiting for a tick nobody publishes is healthy."""
        settings = '[default]\nscheduler_mode = "event"\nevent_bus = "nats"\nnats_url = "nats://b:4222"\napp_name = "demo"\n'
        project = self._with_scheduler(_project(tmp_path, settings=settings))

        issues, _, notices = self._findings(project)

        assert issues == []
        assert any("CronJob" in notice for notice in notices)

    def test_event_mode_without_a_bus_in_this_file_is_a_notice(self, tmp_path: Path) -> None:
        """S27 -- event_bus is a process-scope key: the group's settings or the environment may set it."""
        project = self._with_scheduler(_project(tmp_path, settings='[default]\nscheduler_mode = "event"\n'))

        issues, _, notices = self._findings(project)

        assert issues == []
        assert any("no 'event_bus' is set" in notice for notice in notices)

    def test_event_mode_on_a_bus_that_cannot_deliver_a_tick_is_an_issue(self, tmp_path: Path) -> None:
        """S27 (a) -- the runtime needs a topic transport; 'sessions' is present but delivers no tick."""
        settings = '[default]\nscheduler_mode = "event"\nevent_bus = "sessions"\n'
        project = self._with_scheduler(_project(tmp_path, settings=settings))

        issues, _, _ = self._findings(project)

        assert any("'event_bus' is 'sessions', which cannot deliver a tick" in issue for issue in issues)

    def test_the_mode_is_read_as_the_runtime_reads_it(self, tmp_path: Path) -> None:
        """S27 (e) -- 'Event' runs; validate refused it."""
        settings = '[default]\nscheduler_mode = " Event "\nevent_bus = "nats"\nnats_url = "nats://b:4222"\napp_name = "demo"\n'
        project = self._with_scheduler(_project(tmp_path, settings=settings))

        issues, _, _ = self._findings(project)

        assert issues == []

    def test_an_environment_override_counts(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """S27 (c) -- a value the deployment supplies is not missing."""
        monkeypatch.setenv("DYNACONF_SCHEDULER_MODE", "event")
        monkeypatch.setenv("DYNACONF_EVENT_BUS", "nats")
        monkeypatch.setenv("DYNACONF_NATS_URL", "nats://b:4222")
        project = self._with_scheduler(_project(tmp_path, settings='[default]\napp_name = "demo"\n'))

        issues, _, notices = self._findings(project)

        assert issues == []
        assert not any("no 'event_bus'" in notice for notice in notices)

    def test_in_process_mode_without_a_cache_says_every_replica_runs_every_tick(self, tmp_path: Path) -> None:
        settings = '[default]\nscheduler_mode = "in_process"\n'
        project = self._with_scheduler(_project(tmp_path, settings=settings))

        _, _, notices = self._findings(project)

        assert len(notices) == 1
        assert "every replica runs every tick" in notices[0]

    def test_in_process_mode_with_a_redis_cache_is_quiet(self, tmp_path: Path) -> None:
        settings = '[default]\nscheduler_mode = "in_process"\n[default.cache]\nbackend = "redis"\n'
        main = "agent = AppBuilder().with_cache()\n"
        project = self._with_scheduler(_project(tmp_path, settings=settings, main=main))

        _, _, notices = self._findings(project)

        assert notices == []
