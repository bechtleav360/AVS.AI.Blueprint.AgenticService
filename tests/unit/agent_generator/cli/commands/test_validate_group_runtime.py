"""`asbs validate --group` reports what the image's process refuses or warns about at startup.

The group file is resolved by the runtime's own ``GroupConfig.resolve_at`` against a stub
environment, so its refusals arrive in the runtime's words. The per-agent checks run on each
agent's resolved view: its own scope (the image's ``[default.<agent>]``, its ``.secrets.toml``, its
``settings.toml``), then the image's root keys -- the order ``Config`` resolves them in.
"""

from pathlib import Path

import pytest

from blueprint.agent_generator.cli.commands.validate_group import image_findings

DECLARATION = "from blueprint.agents.app_builder import AppBuilder\n\nagent = AppBuilder()\n"
CACHED = "from blueprint.agents.app_builder import AppBuilder\n\nagent = AppBuilder().with_cache()\n"


@pytest.fixture(autouse=True)
def _no_ambient_group(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "BLUEPRINT_GROUP",
        "BLUEPRINT_AGENTS",
        "BLUEPRINT_CRITICAL_AGENTS",
        "BLUEPRINT_GROUP_CONFIG",
        "BLUEPRINT_AGENT_MAP",
        "DYNACONF_APP_ENVIRONMENT",
        "DYNACONF_NATS_URL",
    ):
        monkeypatch.delenv(name, raising=False)


def _agent(image: Path, name: str, *, settings: str = '[default]\nmodel_name = "x"\n', main: str = DECLARATION) -> Path:
    root = image / "agents" / name
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / "main.py").write_text(main, encoding="utf-8")
    (root / "settings.toml").write_text(settings, encoding="utf-8")
    return root


def _image(tmp_path: Path, *names: str, image_settings: str = '[default]\napp_name = "group"\n') -> Path:
    entries = "".join(f'[agents.{name}]\nroot = "agents/{name}"\nmodule = "agents.{name}.src.main:agent"\n' for name in names)
    (tmp_path / "agents.toml").write_text(entries, encoding="utf-8")
    (tmp_path / "settings.toml").write_text(image_settings, encoding="utf-8")
    for name in names:
        if not (tmp_path / "agents" / name).is_dir():
            _agent(tmp_path, name)
    return tmp_path


def _findings(image: Path, **kwargs: object) -> tuple[list[str], list[str], list[str]]:
    return image_findings(image, image / "agents.toml", **kwargs)  # type: ignore[arg-type]


class TestTheAgentMap:
    def test_an_empty_map_is_an_issue(self, tmp_path: Path) -> None:
        """Audit 1e: a warning, for an image that cannot start."""
        (tmp_path / "agents.toml").write_text("# nothing yet\n", encoding="utf-8")

        issues, _, _ = _findings(tmp_path)

        assert any("declares no [agents.<name>] entries" in issue for issue in issues)

    def test_a_module_missing_from_the_image_is_an_issue(self, tmp_path: Path) -> None:
        image = _image(tmp_path, "orders")
        (image / "agents.toml").write_text(
            '[agents.orders]\nroot = "agents/orders"\nmodule = "agents.orders.src.nowhere:agent"\n', encoding="utf-8"
        )

        issues, _, _ = _findings(image)

        assert any("is not a module in this image" in issue for issue in issues)

    def test_a_module_that_assigns_no_such_attribute_is_an_issue(self, tmp_path: Path) -> None:
        image = _image(tmp_path, "orders")
        (image / "agents.toml").write_text(
            '[agents.orders]\nroot = "agents/orders"\nmodule = "agents.orders.src.main:registration"\n', encoding="utf-8"
        )

        issues, _, _ = _findings(image)

        assert any("assigns no 'registration'" in issue for issue in issues)


class TestTheGroupFile:
    """Audit 1a-1d: the group file was never read."""

    def _with_groups(self, tmp_path: Path, groups: str) -> Path:
        image = _image(tmp_path, "orders", "billing")
        (image / "deployment-groups.yaml").write_text(groups, encoding="utf-8")
        return image

    def test_no_group_file_and_no_environment_is_a_notice_not_an_issue(self, tmp_path: Path) -> None:
        issues, _, notices = _findings(_image(tmp_path, "orders"))

        assert issues == []
        assert any("No group file" in notice for notice in notices)

    def test_a_well_formed_file_passes(self, tmp_path: Path) -> None:
        image = self._with_groups(tmp_path, "groups:\n  - name: finance\n    agents: [orders, billing]\n    critical_agents: [orders]\n")

        issues, warnings, _ = _findings(image)

        assert (issues, warnings) == ([], [])

    def test_a_scalar_agent_list_is_an_issue(self, tmp_path: Path) -> None:
        image = self._with_groups(tmp_path, "groups:\n  - name: finance\n    agents: orders\n")

        issues, _, _ = _findings(image)

        assert any("must be a list of agent names" in issue for issue in issues)

    def test_a_duplicate_group_name_is_an_issue(self, tmp_path: Path) -> None:
        image = self._with_groups(tmp_path, "groups:\n  - name: a\n    agents: [orders]\n  - name: a\n    agents: [billing]\n")

        issues, _, _ = _findings(image)

        assert any("more than once" in issue for issue in issues)

    def test_an_unknown_critical_name_is_an_issue(self, tmp_path: Path) -> None:
        image = self._with_groups(tmp_path, "groups:\n  - name: finance\n    agents: [orders]\n    critical_agents: [ordres]\n")

        issues, _, _ = _findings(image)

        assert any("'critical_agents'" in issue and "ordres" in issue for issue in issues)

    def test_a_critical_agent_missing_from_the_map_is_an_issue(self, tmp_path: Path) -> None:
        image = self._with_groups(tmp_path, "groups:\n  - name: finance\n    agents: [orders, shipping]\n")

        issues, _, _ = _findings(image)

        assert any("names agent 'shipping', which this image does not contain" in issue for issue in issues)

    def test_a_non_critical_agent_missing_from_the_map_is_a_warning(self, tmp_path: Path) -> None:
        image = self._with_groups(tmp_path, "groups:\n  - name: finance\n    agents: [orders, shipping]\n    critical_agents: [orders]\n")

        issues, warnings, _ = _findings(image)

        assert issues == []
        assert any("'shipping'" in warning and "skipped" in warning for warning in warnings)

    def test_an_empty_group_is_an_issue(self, tmp_path: Path) -> None:
        image = self._with_groups(tmp_path, "groups:\n  - name: finance\n    agents: []\n")

        issues, _, _ = _findings(image)

        assert any("No agents were resolved" in issue for issue in issues)

    def test_every_group_of_a_multi_group_file_is_checked(self, tmp_path: Path) -> None:
        image = self._with_groups(tmp_path, "groups:\n  - name: a\n    agents: [orders]\n  - name: b\n    agents: [nobody]\n")

        issues, _, _ = _findings(image)

        assert len(issues) == 1
        assert "Group 'b'" in issues[0]

    def test_a_group_name_restricts_the_check_to_that_group(self, tmp_path: Path) -> None:
        image = self._with_groups(tmp_path, "groups:\n  - name: a\n    agents: [orders]\n  - name: b\n    agents: [nobody]\n")

        issues, _, _ = _findings(image, group_name="a")

        assert issues == []

    def test_the_file_can_be_named_explicitly(self, tmp_path: Path) -> None:
        image = _image(tmp_path, "orders")
        (image / "deploy").mkdir()
        (image / "deploy" / "finance.yaml").write_text("groups:\n  - name: finance\n    agents: orders\n", encoding="utf-8")

        issues, _, _ = _findings(image, group_config="deploy/finance.yaml")

        assert any("must be a list of agent names" in issue for issue in issues)

    def test_an_agent_list_from_the_environment_is_resolved_too(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BLUEPRINT_AGENTS", "orders,shipping")

        issues, _, _ = _findings(_image(tmp_path, "orders"))

        assert any("'shipping'" in issue for issue in issues)


class TestSettingsTheMergeDrops:
    """Audit 3b/3d: what the merge refuses or drops, including the agent's .secrets.toml."""

    def test_a_deployment_identity_key_in_an_agent_file_is_warned(self, tmp_path: Path) -> None:
        image = _image(tmp_path, "orders")
        (image / "agents" / "orders" / "settings.toml").write_text('[default]\nhostname = "pod-1"\n', encoding="utf-8")

        _, warnings, _ = _findings(image)

        assert any("hostname" in warning for warning in warnings)

    def test_a_process_key_in_an_agent_secrets_file_is_warned_without_its_value(self, tmp_path: Path) -> None:
        image = _image(tmp_path, "orders")
        (image / "agents" / "orders" / ".secrets.toml").write_text(
            '[default]\napp_port = 9000\nmodel_api_key = "s3cr3t"\n', encoding="utf-8"
        )

        _, warnings, _ = _findings(image)

        found = [warning for warning in warnings if "app_port" in warning]
        assert found and ".secrets.toml" in found[0]
        assert not any("s3cr3t" in warning or "9000" in warning for warning in warnings)

    def test_a_secrets_file_scoped_under_the_agents_own_name_is_an_issue(self, tmp_path: Path) -> None:
        image = _image(tmp_path, "orders")
        (image / "agents" / "orders" / ".secrets.toml").write_text('[default.orders]\nmodel_api_key = "x"\n', encoding="utf-8")

        issues, _, _ = _findings(image)

        assert any("scopes its own settings under its own name" in issue and ".secrets.toml" in issue for issue in issues)

    def test_an_image_key_named_like_an_agent_that_is_not_a_table_is_an_issue(self, tmp_path: Path) -> None:
        image = _image(tmp_path, "orders", image_settings='[default]\napp_name = "group"\norders = "scalar"\n')

        issues, _, _ = _findings(image)

        assert any("cannot have settings of its own" in issue for issue in issues)


class TestPerAgentRuntimeChecks:
    def test_an_image_nats_value_the_runtime_refuses_is_an_issue(self, tmp_path: Path) -> None:
        """Audit 12f: '--group' parsed no NATS key at all."""
        image = _image(tmp_path, "orders", image_settings='[default]\napp_name = "group"\nnats_handler_timeout = -1\n')

        issues, _, _ = _findings(image)

        assert len([issue for issue in issues if "nats_handler_timeout" in issue]) == 1, "reported once, not per agent"

    def test_an_agent_nats_value_is_reported_for_that_agent(self, tmp_path: Path) -> None:
        image = _image(tmp_path, "orders")
        (image / "agents" / "orders" / "settings.toml").write_text("[default]\nnats_max_concurrent_runs = 0\n", encoding="utf-8")

        issues, _, _ = _findings(image)

        assert any(issue.startswith("Agent 'orders'") and "nats_max_concurrent_runs" in issue for issue in issues)

    def test_dedup_without_a_ttl_in_an_agent_is_an_issue(self, tmp_path: Path) -> None:
        image = _image(tmp_path, "orders")
        _agent(image, "orders", settings="[default]\nidempotency_enabled = true\n", main=CACHED)
        (image / "agents" / "orders" / "src" / "handlers").mkdir()
        (image / "agents" / "orders" / "src" / "handlers" / "order_handler.py").write_text("# h\n", encoding="utf-8")

        issues, _, _ = _findings(image)

        assert any("Agent 'orders'" in issue and "'idempotency_ttl' is not set" in issue for issue in issues)

    def test_nats_without_a_url_is_a_notice_per_consuming_agent(self, tmp_path: Path) -> None:
        """B2 -- the deployment injects nats_url when the container starts; a build-time check cannot see it."""
        image = _image(tmp_path, "orders", image_settings='[default]\napp_name = "group"\nevent_bus = "nats"\n')
        (image / "agents" / "orders" / "src" / "handlers").mkdir()
        (image / "agents" / "orders" / "src" / "handlers" / "order_handler.py").write_text("# h\n", encoding="utf-8")

        issues, _, notices = _findings(image)

        assert not any("'nats_url' is not set" in issue for issue in issues)
        assert any(
            "Agent 'orders'" in notice and "'nats_url' is not set" in notice and "unless the deployment" in notice for notice in notices
        )

    def test_a_shared_dapr_topic_without_dedup_is_warned(self, tmp_path: Path) -> None:
        """Audit 6: the runtime warns at startup that one retry redelivers to every agent."""
        image = _image(tmp_path, "orders", "billing", image_settings='[default]\napp_name = "group"\nevent_bus = "dapr"\n')
        source = "class H:\n    def get_subscribed_topics(self) -> list[str]:\n        return ['invoices']\n"
        for name in ("orders", "billing"):
            (image / "agents" / name / "src" / "handlers").mkdir()
            (image / "agents" / name / "src" / "handlers" / "invoice_handler.py").write_text(source, encoding="utf-8")

        _, warnings, _ = _findings(image)

        assert any("Topic 'invoices' is declared by agents" in warning for warning in warnings)

    def test_an_agents_crontab_is_checked_in_its_mode(self, tmp_path: Path) -> None:
        image = _image(tmp_path, "orders")
        _agent(image, "orders", settings='[default]\nscheduler_mode = "in_process"\n', main=CACHED)
        schedulers = image / "agents" / "orders" / "src" / "schedulers"
        schedulers.mkdir()
        (schedulers / "nightly_scheduler.py").write_text(
            "class S:\n    def __init__(self):\n        super().__init__(crontab='0 0 * * 7')\n", encoding="utf-8"
        )

        issues, _, _ = _findings(image)

        assert any("Agent 'orders'" in issue and "names day 7" in issue for issue in issues)
