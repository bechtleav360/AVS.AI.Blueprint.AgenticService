"""Resolving which agents a process hosts, from a mounted file and from the environment.

Both mechanisms are required and neither is preferred (spec sec. 5.1): a file suits a ConfigMap
mount and local development, environment variables suit ``docker run`` and CI and are what makes
Kubernetes roll a Deployment when the group changes. They compose, key by key.

The failures matter more than the successes here. A group that resolves to the wrong contents
produces a pod that passes its probes with a queue nobody is consuming, so every way of getting
it wrong has to fail while the process is starting.
"""

from pathlib import Path

import pytest

from blueprint.agents.config import Config
from blueprint.agents.group_config import AgentSpec, GroupConfig, GroupConfigError

AGENT_MAP = """
[agents.invoice]
module = "agents.invoice.declaration:registration"

[agents.order]
module = "agents.order.declaration:registration"

[agents.dunning]
module = "agents.dunning.declaration:registration"
"""

GROUP_FILE = """
groups:
  - name: finance
    agents: [invoice, order]
    cache_names: [sessions]
  - name: contracts
    agents: [dunning]
"""


@pytest.fixture
def project(tmp_path: Path) -> Config:
    """A project root with an agent map, a group file and a settings tree."""
    (tmp_path / "agents.toml").write_text(AGENT_MAP)
    (tmp_path / "deployment-groups.yaml").write_text(GROUP_FILE)
    settings = tmp_path / "settings.toml"
    settings.write_text('[development]\napp_environment = "development"\napp_name = "the-process"\n')
    return Config(settings_files=[str(settings)], root_path=str(tmp_path))


class TestFromTheGroupFile:
    def test_the_named_group_is_loaded(self, project: Config) -> None:
        group = GroupConfig.resolve(project, environ={"BLUEPRINT_GROUP": "finance"})

        assert group.name == "finance"
        assert group.agent_names == ("invoice", "order")

    def test_the_agents_module_comes_from_the_image(self, project: Config) -> None:
        """What an agent *is* belongs to the image; only which agents run is the deployment's."""
        group = GroupConfig.resolve(project, environ={"BLUEPRINT_GROUP": "finance"})

        assert group.agents[0] == AgentSpec(name="invoice", module="agents.invoice.declaration:registration", critical=True)

    def test_declared_caches_are_carried(self, project: Config) -> None:
        """A cache is process-wide, so it is the group's to declare rather than an agent's."""
        group = GroupConfig.resolve(project, environ={"BLUEPRINT_GROUP": "finance"})

        assert group.cache_names == ("sessions",)

    def test_another_group_in_the_same_file(self, project: Config) -> None:
        group = GroupConfig.resolve(project, environ={"BLUEPRINT_GROUP": "contracts"})

        assert group.agent_names == ("dunning",)

    def test_a_single_group_file_needs_no_group_name(self, tmp_path: Path) -> None:
        (tmp_path / "agents.toml").write_text(AGENT_MAP)
        (tmp_path / "deployment-groups.yaml").write_text("groups:\n  - name: only\n    agents: [invoice]\n")
        settings = tmp_path / "settings.toml"
        settings.write_text('[development]\napp_environment = "development"\n')
        config = Config(settings_files=[str(settings)], root_path=str(tmp_path))

        assert GroupConfig.resolve(config, environ={}).name == "only"

    def test_several_groups_and_no_name_is_ambiguous(self, project: Config) -> None:
        with pytest.raises(GroupConfigError, match="which one to run is ambiguous"):
            GroupConfig.resolve(project, environ={})

    def test_an_unknown_group_name_is_refused(self, project: Config) -> None:
        with pytest.raises(GroupConfigError, match="Group 'nope' is not declared"):
            GroupConfig.resolve(project, environ={"BLUEPRINT_GROUP": "nope"})

    def test_the_refusal_lists_what_the_file_has(self, project: Config) -> None:
        with pytest.raises(GroupConfigError, match="contracts, finance"):
            GroupConfig.resolve(project, environ={"BLUEPRINT_GROUP": "nope"})

    def test_a_configured_path_is_honoured(self, project: Config, tmp_path: Path) -> None:
        """The path is configuration, so one image serves a mount, a bind mount and a repo file."""
        elsewhere = tmp_path / "mounted" / "group.yaml"
        elsewhere.parent.mkdir()
        elsewhere.write_text("groups:\n  - name: mounted\n    agents: [order]\n")

        group = GroupConfig.resolve(project, environ={"BLUEPRINT_GROUP_CONFIG": str(elsewhere)})

        assert (group.name, group.agent_names) == ("mounted", ("order",))

    def test_a_malformed_file_is_an_error(self, project: Config, tmp_path: Path) -> None:
        """An absent file is fine; a mounted one that cannot be parsed was meant to be used."""
        broken = tmp_path / "broken.yaml"
        broken.write_text("groups: [oops\n")

        with pytest.raises(GroupConfigError, match="could not be read"):
            GroupConfig.resolve(project, environ={"BLUEPRINT_GROUP_CONFIG": str(broken)})

    def test_a_file_without_groups_is_an_error(self, project: Config, tmp_path: Path) -> None:
        empty = tmp_path / "empty.yaml"
        empty.write_text("something_else: 1\n")

        with pytest.raises(GroupConfigError, match="declares no 'groups' list"):
            GroupConfig.resolve(project, environ={"BLUEPRINT_GROUP_CONFIG": str(empty)})


class TestFromTheEnvironmentAlone:
    def test_agents_can_come_from_the_environment_with_no_file(self, tmp_path: Path) -> None:
        """The docker run and CI shape: no file, no mount."""
        (tmp_path / "agents.toml").write_text(AGENT_MAP)
        settings = tmp_path / "settings.toml"
        settings.write_text('[development]\napp_environment = "development"\n')
        config = Config(settings_files=[str(settings)], root_path=str(tmp_path))

        group = GroupConfig.resolve(config, environ={"BLUEPRINT_AGENTS": "invoice,dunning", "BLUEPRINT_GROUP": "adhoc"})

        assert (group.name, group.agent_names) == ("adhoc", ("invoice", "dunning"))

    def test_whitespace_around_names_is_tolerated(self, project: Config) -> None:
        group = GroupConfig.resolve(project, environ={"BLUEPRINT_AGENTS": " invoice , order "})

        assert group.agent_names == ("invoice", "order")

    def test_a_group_with_no_name_is_called_ungrouped(self, project: Config) -> None:
        """An empty segment in the connection name and the telemetry resource reads as a bug."""
        group = GroupConfig.resolve(project, environ={"BLUEPRINT_AGENTS": "invoice"})

        assert group.name == "ungrouped"

    def test_no_agents_anywhere_is_an_error(self, tmp_path: Path) -> None:
        (tmp_path / "agents.toml").write_text(AGENT_MAP)
        settings = tmp_path / "settings.toml"
        settings.write_text('[development]\napp_environment = "development"\n')
        config = Config(settings_files=[str(settings)], root_path=str(tmp_path))

        with pytest.raises(GroupConfigError, match="No agents were resolved"):
            GroupConfig.resolve(config, environ={})


class TestPrecedence:
    def test_the_environment_overrides_the_files_agent_list(self, project: Config) -> None:
        """Key by key: a Deployment changes the list without restating the group."""
        group = GroupConfig.resolve(project, environ={"BLUEPRINT_GROUP": "finance", "BLUEPRINT_AGENTS": "dunning"})

        assert group.agent_names == ("dunning",)

    def test_the_files_other_values_survive_the_override(self, project: Config) -> None:
        group = GroupConfig.resolve(project, environ={"BLUEPRINT_GROUP": "finance", "BLUEPRINT_AGENTS": "dunning"})

        assert (group.name, group.cache_names) == ("finance", ("sessions",))

    def test_the_source_of_each_value_is_logged(self, project: Config, caplog: pytest.LogCaptureFixture) -> None:
        """The first question asked of a group with the wrong contents is where they came from."""
        with caplog.at_level("INFO", logger="blueprint.agents.group_config"):
            GroupConfig.resolve(project, environ={"BLUEPRINT_GROUP": "finance", "BLUEPRINT_AGENTS": "dunning"})

        assert "'agents' resolved from $BLUEPRINT_AGENTS" in caplog.text
        assert "'name' resolved from file" in caplog.text

    def test_the_resolved_group_is_logged(self, project: Config, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level("INFO", logger="blueprint.agents.group_config"):
            GroupConfig.resolve(project, environ={"BLUEPRINT_GROUP": "finance"})

        assert "Resolved group 'finance' with 2 agent(s): invoice, order" in caplog.text


class TestCriticality:
    def test_every_agent_is_critical_by_default(self, project: Config) -> None:
        """A group missing a consumer is worse than no pod: the default cannot be permissive."""
        group = GroupConfig.resolve(project, environ={"BLUEPRINT_GROUP": "finance"})

        assert all(agent.critical for agent in group.agents)

    def test_a_critical_subset_marks_only_those(self, project: Config) -> None:
        group = GroupConfig.resolve(project, environ={"BLUEPRINT_GROUP": "finance", "BLUEPRINT_CRITICAL_AGENTS": "invoice"})

        assert {agent.name: agent.critical for agent in group.agents} == {"invoice": True, "order": False}

    def test_the_file_can_declare_the_subset(self, project: Config, tmp_path: Path) -> None:
        path = tmp_path / "with-critical.yaml"
        path.write_text("groups:\n  - name: finance\n    agents: [invoice, order]\n    critical_agents: [order]\n")

        group = GroupConfig.resolve(project, environ={"BLUEPRINT_GROUP_CONFIG": str(path)})

        assert {agent.name: agent.critical for agent in group.agents} == {"invoice": False, "order": True}


class TestAgainstTheAgentMap:
    def test_an_agent_the_image_does_not_contain_is_refused(self, project: Config) -> None:
        """The seam that turns a config typo into a crash-loop with a readable message."""
        with pytest.raises(GroupConfigError, match="which this image does not contain"):
            GroupConfig.resolve(project, environ={"BLUEPRINT_AGENTS": "invoice,typo"})

    def test_the_refusal_lists_what_the_image_has(self, project: Config) -> None:
        with pytest.raises(GroupConfigError, match="dunning, invoice, order"):
            GroupConfig.resolve(project, environ={"BLUEPRINT_AGENTS": "typo"})

    def test_a_non_critical_missing_agent_is_skipped(self, project: Config, caplog: pytest.LogCaptureFixture) -> None:
        """The deployment said it would rather run the rest, so it does -- loudly."""
        with caplog.at_level("ERROR", logger="blueprint.agents.group_config"):
            group = GroupConfig.resolve(project, environ={"BLUEPRINT_AGENTS": "invoice,typo", "BLUEPRINT_CRITICAL_AGENTS": "invoice"})

        assert group.agent_names == ("invoice",)
        assert "is not in this image's agent map" in caplog.text

    def test_a_missing_agent_map_is_an_error(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.toml"
        settings.write_text('[development]\napp_environment = "development"\n')
        config = Config(settings_files=[str(settings)], root_path=str(tmp_path))

        with pytest.raises(GroupConfigError, match="No agent map at"):
            GroupConfig.resolve(config, environ={"BLUEPRINT_AGENTS": "invoice"})

    def test_an_entry_without_a_module_is_an_error(self, project: Config, tmp_path: Path) -> None:
        path = tmp_path / "bad-map.toml"
        path.write_text("[agents.invoice]\ndescription = 'no module'\n")

        with pytest.raises(GroupConfigError, match="has no 'module'"):
            GroupConfig.resolve(project, environ={"BLUEPRINT_AGENTS": "invoice", "BLUEPRINT_AGENT_MAP": str(path)})

    def test_an_empty_agent_map_is_an_error(self, project: Config, tmp_path: Path) -> None:
        path = tmp_path / "empty-map.toml"
        path.write_text("# nothing here\n")

        with pytest.raises(GroupConfigError, match="declares no \\[agents"):
            GroupConfig.resolve(project, environ={"BLUEPRINT_AGENTS": "invoice", "BLUEPRINT_AGENT_MAP": str(path)})


class TestAgentNamesAreAgentNames:
    def test_a_name_that_cannot_be_a_namespace_is_refused(self, project: Config) -> None:
        """It becomes a namespace, so rejecting it here names the group file instead of a constructor."""
        with pytest.raises(GroupConfigError, match="cannot be a namespace"):
            GroupConfig.resolve(project, environ={"BLUEPRINT_AGENTS": "Invoice"})

    def test_a_name_with_a_hyphen_is_refused(self, project: Config) -> None:
        with pytest.raises(GroupConfigError, match="cannot be a namespace"):
            GroupConfig.resolve(project, environ={"BLUEPRINT_AGENTS": "in-voice"})

    def test_the_same_agent_twice_is_refused(self, project: Config) -> None:
        with pytest.raises(GroupConfigError, match="more than once"):
            GroupConfig.resolve(project, environ={"BLUEPRINT_AGENTS": "invoice,invoice"})


class TestTheValueObject:
    def test_it_performs_no_io_once_constructed(self) -> None:
        """Constructed literally, so a test states a composition instead of arranging files."""
        group = GroupConfig(name="finance", agents=(AgentSpec(name="invoice", module="pkg:reg"),))

        assert (group.name, group.agent_names, group.cache_names) == ("finance", ("invoice",), ())

    def test_it_is_frozen(self) -> None:
        group = GroupConfig(name="finance", agents=())

        with pytest.raises(Exception, match="cannot assign to field"):
            group.name = "other"  # type: ignore[misc]
