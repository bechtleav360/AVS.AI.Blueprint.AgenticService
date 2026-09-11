"""`asbs validate`'s group gates -- what a project must state before it can be grouped.

The gates exist because there is no `asbs migrate`: `main.py` is the developer's own declaration,
and a tool that rewrites it either guesses at intent or fails on anything hand-edited. A checklist
plus a validate that names what is missing is the honest shape, so what these tests hold is that
each thing it can name, it does.
"""

from pathlib import Path

from blueprint.agent_generator.cli.commands.validate import _group_findings

DECLARATION = "from blueprint.agents.app_builder import AppBuilder\n\nagent = AppBuilder()\n"


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


def _agent(name: str = "orders", module: str = "src.main:agent") -> str:
    return f'[agents.{name}]\nmodule = "{module}"\n'


class TestTheAgentMap:
    """The map is how a name reaches code; the gate is everything that stops it."""

    def test_a_project_without_one_is_told_the_three_changes(self, tmp_path: Path) -> None:
        issues, warnings, _ = _group_findings(_project(tmp_path))

        assert not issues, "A project deployed on its own is not broken, so this is never an issue."
        assert len(warnings) == 1
        assert "src/main.py" in warnings[0]
        assert "Dockerfile" in warnings[0]
        assert "agents.toml" in warnings[0]

    def test_a_well_formed_map_passes_silently(self, tmp_path: Path) -> None:
        issues, warnings, _ = _group_findings(_project(tmp_path, agent_map=_agent()))

        assert (issues, warnings) == ([], [])

    def test_an_unparseable_map_is_reported(self, tmp_path: Path) -> None:
        issues, _, _ = _group_findings(_project(tmp_path, agent_map="[agents.orders\nbroken\n"))

        assert len(issues) == 1
        assert "could not be read" in issues[0]

    def test_a_map_with_no_agents_is_reported(self, tmp_path: Path) -> None:
        issues, _, _ = _group_findings(_project(tmp_path, agent_map="# nothing\n"))

        assert "declares no [agents.<name>] entries" in issues[0]

    def test_an_entry_without_a_module_is_reported(self, tmp_path: Path) -> None:
        issues, _, _ = _group_findings(_project(tmp_path, agent_map="[agents.orders]\ncritical = true\n"))

        assert "has no 'module'" in issues[0]

    def test_a_module_that_names_no_attribute_is_reported(self, tmp_path: Path) -> None:
        issues, _, _ = _group_findings(_project(tmp_path, agent_map=_agent(module="src.main")))

        assert "does not say which attribute" in issues[0]

    def test_a_name_that_cannot_be_a_namespace_is_reported(self, tmp_path: Path) -> None:
        """It becomes a queue group, a durable, a cache partition and a service.name."""
        issues, _, _ = _group_findings(_project(tmp_path, agent_map=_agent(name="order-eu")))

        assert "cannot be a namespace" in issues[0]

    def test_a_module_that_is_not_in_the_project_is_reported(self, tmp_path: Path) -> None:
        issues, _, _ = _group_findings(_project(tmp_path, agent_map=_agent(module="src.nowhere:agent")))

        assert "is not a module in this project" in issues[0]

    def test_a_module_that_declares_no_such_attribute_is_reported(self, tmp_path: Path) -> None:
        """The attribute is the AppBuilder the host builds; without it the process never starts."""
        issues, _, _ = _group_findings(_project(tmp_path, agent_map=_agent(module="src.main:registration")))

        assert "assigns no 'registration'" in issues[0]

    def test_a_package_declaration_resolves_too(self, tmp_path: Path) -> None:
        package = tmp_path / "src" / "orders"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text(DECLARATION, encoding="utf-8")

        issues, _, _ = _group_findings(_project(tmp_path, agent_map=_agent(module="src.orders:agent")))

        assert issues == []


class TestSettingsThatWillNotSurviveGrouping:
    """An agent's settings are read from its declaration's directory, and scoped to it."""

    def test_a_project_hosted_alone_is_not_told_about_scoping(self, tmp_path: Path) -> None:
        """Its settings.toml *is* the process's own file, so neither rule applies to it yet."""
        project = _project(tmp_path, agent_map=_agent(), settings="[default]\napp_port = 8000\n")

        _, warnings, _ = _group_findings(project)

        assert warnings == []

    def test_an_agent_shipping_no_settings_of_its_own_is_told_where_they_go(self, tmp_path: Path) -> None:
        project = _project(tmp_path, agent_map=_agent() + _agent(name="billing", module="src.billing:agent"))
        (tmp_path / "src" / "billing").mkdir()
        (tmp_path / "src" / "billing" / "__init__.py").write_text(DECLARATION, encoding="utf-8")

        _, warnings, _ = _group_findings(project)

        assert len(warnings) == 2
        assert all("ships no settings of its own" in warning for warning in warnings)

    def test_a_declaration_at_the_project_root_keeps_the_process_settings_file(self, tmp_path: Path) -> None:
        """`main:agent` puts the agent's settings file where the process's own already is."""
        project = _project(tmp_path, agent_map=_agent(module="main:agent") + _agent(name="billing", module="src.billing:agent"))
        (tmp_path / "main.py").write_text(DECLARATION, encoding="utf-8")
        (tmp_path / "settings.toml").write_text("[default]\napp_port = 8000\n", encoding="utf-8")
        billing = tmp_path / "src" / "billing"
        billing.mkdir(parents=True)
        (billing / "__init__.py").write_text(DECLARATION, encoding="utf-8")
        (billing / "settings.toml").write_text('[default]\nmodel_name = "y"\n', encoding="utf-8")

        _, warnings, _ = _group_findings(project)

        assert warnings == [], "The merge leaves the process's own settings file at the root rather than scoping it."

    def test_a_process_scope_key_in_a_fragment_is_named(self, tmp_path: Path) -> None:
        """One process binds one port and speaks one bus, so these are dropped at startup."""
        project = _project(tmp_path, agent_map=_agent() + _agent(name="billing", module="src.billing:agent"))
        (tmp_path / "src" / "settings.toml").write_text(
            '[default]\napp_port = 8000\nevent_bus = "nats"\nmodel_name = "x"\n', encoding="utf-8"
        )
        billing = tmp_path / "src" / "billing"
        billing.mkdir()
        (billing / "__init__.py").write_text(DECLARATION, encoding="utf-8")
        (billing / "settings.toml").write_text('[default]\nmodel_name = "y"\n', encoding="utf-8")

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

    def test_a_project_with_no_schedulers_is_asked_nothing(self, tmp_path: Path) -> None:
        issues, _, notices = _group_findings(_project(tmp_path, agent_map=_agent()))

        assert (issues, notices) == ([], [])

    def test_a_scheduler_without_a_mode_is_an_issue(self, tmp_path: Path) -> None:
        """It has no default because neither value is safe to inherit, so build() fails."""
        project = self._with_scheduler(_project(tmp_path, agent_map=_agent(), settings='[default]\napp_name = "demo"\n'))

        issues, _, _ = _group_findings(project)

        assert "no 'scheduler_mode'" in issues[0]

    def test_an_unknown_mode_is_an_issue(self, tmp_path: Path) -> None:
        project = self._with_scheduler(_project(tmp_path, agent_map=_agent(), settings='[default]\nscheduler_mode = "cron"\n'))

        issues, _, _ = _group_findings(project)

        assert "must be one of" in issues[0]

    def test_event_mode_says_that_nothing_here_publishes_the_tick(self, tmp_path: Path) -> None:
        """The silent-failure case: a scheduler waiting for a tick nobody publishes is healthy."""
        settings = '[default]\nscheduler_mode = "event"\nevent_bus = "nats"\n'
        project = self._with_scheduler(_project(tmp_path, agent_map=_agent(), settings=settings))

        issues, _, notices = _group_findings(project)

        assert issues == []
        assert len(notices) == 1
        assert "CronJob" in notices[0]

    def test_event_mode_without_a_bus_is_an_issue(self, tmp_path: Path) -> None:
        """The tick is an ordinary event, so with no transport there is nothing to subscribe to."""
        project = self._with_scheduler(_project(tmp_path, agent_map=_agent(), settings='[default]\nscheduler_mode = "event"\n'))

        issues, _, _ = _group_findings(project)

        assert any("no 'event_bus' is set" in issue for issue in issues)

    def test_in_process_mode_without_a_cache_says_every_replica_runs_every_tick(self, tmp_path: Path) -> None:
        settings = '[default]\nscheduler_mode = "in_process"\n'
        project = self._with_scheduler(_project(tmp_path, agent_map=_agent(), settings=settings))

        _, _, notices = _group_findings(project)

        assert len(notices) == 1
        assert "every replica runs every tick" in notices[0]

    def test_in_process_mode_with_a_cache_is_quiet(self, tmp_path: Path) -> None:
        settings = '[default]\nscheduler_mode = "in_process"\n'
        main = "agent = AppBuilder().with_cache()\n"
        project = self._with_scheduler(_project(tmp_path, agent_map=_agent(), settings=settings, main=main))

        _, _, notices = _group_findings(project)

        assert notices == []
