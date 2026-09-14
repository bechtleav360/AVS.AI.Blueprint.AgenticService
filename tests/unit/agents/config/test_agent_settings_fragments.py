"""An agent's own ``settings.toml`` becomes that agent's scope (spec sec. 5.3, D5).

The requirement behind every case here is the one the whole feature rests on: **only ``main.py``
may differ between a project deployed on its own and the same project hosted as one agent of a
group.** So an agent author keeps writing plain keys -- or a ``[default]`` section, which is what
every scaffolded project has -- in their own directory's file, and the build merges that file
under the agent's scope without the author knowing a scope exists.

Two properties are pinned down. **Isolation**: a fragment can add to its own agent and to nothing
else, so there is no collision with a root key to report and no way for one agent to change what
a neighbour or the process reads. **Precedence**: what is already in the tree -- the group's own
``[default.<agent>]``, or an environment override -- wins, and the fragment fills the gaps.
"""

from pathlib import Path

import pytest

from blueprint.agents.config import Config
from blueprint.agents.config.config import PROCESS_SCOPE_KEYS, ConfigError


@pytest.fixture
def config(tmp_path: Path) -> Config:
    """A group's own settings: defaults for the process, plus one targeted agent value."""
    settings = tmp_path / "settings.toml"
    settings.write_text(
        '[default]\napp_name = "the-process"\napp_port = 8080\napp_environment = "development"\n'
        'model_name = "group-default"\n\n'
        '[default.billing]\nmodel_name = "the-deployment-said-so"\n'
    )
    return Config(settings_files=["settings.toml"], root_path=str(tmp_path))


def fragment(tmp_path: Path, agent: str, body: str) -> Path:
    """Write an agent's own settings file into its own directory, and return the path."""
    directory = tmp_path / "pkg" / agent
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "settings.toml"
    path.write_text(body.replace("\n        ", "\n"))
    return path


class TestWhatAnAgentReads:
    def test_a_plain_key_becomes_that_agents_value(self, config: Config, tmp_path: Path) -> None:
        """Spec sec. 5.3: the author writes ``model_name``, not ``[default.orders]``."""
        config.merge_agent_settings("orders", fragment(tmp_path, "orders", 'model_name = "orders-model"\n'))

        assert config.for_namespace("orders").get("model_name") == "orders-model"

    def test_a_default_section_is_resolved_like_the_processs_own_file(self, config: Config, tmp_path: Path) -> None:
        """Every scaffolded project writes ``[default]``, so a fragment has to mean the same by it."""
        config.merge_agent_settings("orders", fragment(tmp_path, "orders", '[default]\nmodel_name = "orders-model"\n'))

        assert config.for_namespace("orders").get("model_name") == "orders-model"

    def test_the_environment_section_wins_over_default(self, config: Config, tmp_path: Path) -> None:
        body = """
        [default]
        temperature = 0.2

        [development]
        temperature = 0.7
        """
        config.merge_agent_settings("orders", fragment(tmp_path, "orders", body))

        assert config.for_namespace("orders").get("temperature") == 0.7

    def test_another_environments_section_is_not_applied(self, config: Config, tmp_path: Path) -> None:
        body = """
        [default]
        temperature = 0.2

        [production]
        temperature = 0.0
        """
        config.merge_agent_settings("orders", fragment(tmp_path, "orders", body))

        assert config.for_namespace("orders").get("temperature") == 0.2

    def test_a_nested_table_stays_nested(self, config: Config, tmp_path: Path) -> None:
        body = """
        [default.cache]
        cache_dir = ".cache/orders"
        """
        config.merge_agent_settings("orders", fragment(tmp_path, "orders", body))

        assert config.for_namespace("orders").get("cache.cache_dir") == ".cache/orders"

    def test_a_top_level_table_is_a_value_not_an_environment(self, config: Config, tmp_path: Path) -> None:
        """``[cache]`` beside ``[default]`` is this agent's cache configuration."""
        config.merge_agent_settings("orders", fragment(tmp_path, "orders", '[cache]\ncache_dir = ".cache/orders"\n'))

        assert config.for_namespace("orders").get("cache.cache_dir") == ".cache/orders"

    def test_a_root_default_is_still_the_fallback(self, config: Config, tmp_path: Path) -> None:
        """A group's settings are defaults: a key the fragment does not mention still resolves."""
        config.merge_agent_settings("orders", fragment(tmp_path, "orders", "temperature = 0.7\n"))

        assert config.for_namespace("orders").get("model_name") == "group-default"

    def test_the_merged_keys_are_reported(self, config: Config, tmp_path: Path) -> None:
        body = """
        model_name = "orders-model"

        [default.cache]
        cache_dir = ".cache/orders"
        """
        merged = config.merge_agent_settings("orders", fragment(tmp_path, "orders", body))

        assert merged == ("cache", "model_name")


class TestIsolation:
    def test_an_agent_cannot_change_what_the_root_reads(self, config: Config, tmp_path: Path) -> None:
        config.merge_agent_settings("orders", fragment(tmp_path, "orders", 'model_name = "orders-model"\n'))

        assert config.get("model_name") == "group-default"

    def test_an_agent_cannot_change_what_a_neighbour_reads(self, config: Config, tmp_path: Path) -> None:
        config.merge_agent_settings("orders", fragment(tmp_path, "orders", 'model_name = "orders-model"\n'))

        assert config.for_namespace("shipping").get("model_name") == "group-default"

    def test_two_agents_may_declare_the_same_key(self, config: Config, tmp_path: Path) -> None:
        """The reason there is no collision to report: the two never occupy one slot."""
        config.merge_agent_settings("orders", fragment(tmp_path, "orders", 'model_name = "orders-model"\n'))
        config.merge_agent_settings("shipping", fragment(tmp_path, "shipping", 'model_name = "shipping-model"\n'))

        assert (
            config.for_namespace("orders").get("model_name"),
            config.for_namespace("shipping").get("model_name"),
        ) == ("orders-model", "shipping-model")

    def test_a_view_cannot_merge_anything(self, config: Config, tmp_path: Path) -> None:
        """C6: authoring another agent's configuration through a view is the breach reading one is."""
        view = config.for_namespace("orders")

        with pytest.raises(RuntimeError, match="A view resolves its own keys"):
            view.merge_agent_settings("billing", fragment(tmp_path, "billing", 'model_name = "x"\n'))

    def test_the_root_is_not_an_agent(self, config: Config, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="needs an agent's namespace"):
            config.merge_agent_settings("", fragment(tmp_path, "orders", 'model_name = "x"\n'))


class TestPrecedence:
    def test_the_groups_own_value_for_this_agent_wins(self, config: Config, tmp_path: Path) -> None:
        """A deployment that named the agent meant it; the fragment is baked into the image."""
        config.merge_agent_settings("billing", fragment(tmp_path, "billing", 'model_name = "billing-model"\n'))

        assert config.for_namespace("billing").get("model_name") == "the-deployment-said-so"

    def test_the_fragment_fills_what_the_group_left_out(self, config: Config, tmp_path: Path) -> None:
        body = """
        model_name = "billing-model"
        temperature = 0.7
        """
        merged = config.merge_agent_settings("billing", fragment(tmp_path, "billing", body))

        assert merged == ("temperature",)
        assert config.for_namespace("billing").get("temperature") == 0.7

    def test_a_nested_table_is_merged_key_by_key(self, config: Config, tmp_path: Path) -> None:
        """Replacing the table would drop the group's value; being dropped by it would lose the agent's."""
        config._settings["orders"] = {"cache": {"size_limit": 500}}
        body = """
        [default.cache]
        cache_dir = ".cache/orders"
        size_limit = 100
        """
        config.merge_agent_settings("orders", fragment(tmp_path, "orders", body))

        view = config.for_namespace("orders")
        assert (view.get("cache.size_limit"), view.get("cache.cache_dir")) == (500, ".cache/orders")


class TestProcessScopeKeys:
    def test_a_port_is_ignored(self, config: Config, tmp_path: Path) -> None:
        """One process, one HTTP server: a per-agent port is unbindable."""
        config.merge_agent_settings("orders", fragment(tmp_path, "orders", "app_port = 8000\n"))

        assert (config.get("app_port"), config.for_namespace("orders").get("app_port")) == (8080, 8080)

    def test_it_is_reported_with_the_file_and_the_value_in_force(self, config: Config, tmp_path: Path, caplog) -> None:
        """The MUST this softens exists so the author can discover the value is inert."""
        path = fragment(tmp_path, "orders", "app_port = 8000\n")

        with caplog.at_level("WARNING", logger="blueprint.agents.config.config"):
            config.merge_agent_settings("orders", path)

        assert "Agent 'orders' sets 'app_port'" in caplog.text
        assert str(path) in caplog.text
        assert "the group's own value (8080) is used" in caplog.text

    def test_the_report_says_when_the_group_sets_nothing(self, config: Config, tmp_path: Path, caplog) -> None:
        with caplog.at_level("WARNING", logger="blueprint.agents.config.config"):
            config.merge_agent_settings("orders", fragment(tmp_path, "orders", 'log_level = "DEBUG"\n'))

        assert "the group's settings do not set it" in caplog.text

    def test_an_existing_projects_file_is_hosted_unchanged(self, config: Config, tmp_path: Path) -> None:
        """Every example project in this repository writes these three keys. Raising would fork the file."""
        body = """
        [default]
        app_name = "Orders standalone"
        app_port = 8000
        app_environment = "development"
        log_level = "INFO"
        model_name = "orders-model"
        """
        merged = config.merge_agent_settings("orders", fragment(tmp_path, "orders", body))

        assert merged == ("app_name", "model_name")

    def test_display_metadata_is_the_agents_own(self, config: Config, tmp_path: Path) -> None:
        """A scoped app_name is read -- the NATS queue group falls back to it -- so it is not refused."""
        config.merge_agent_settings("orders", fragment(tmp_path, "orders", 'app_name = "Orders standalone"\n'))

        assert config.for_namespace("orders").get("app_name") == "Orders standalone"
        assert config.get("app_name") == "the-process"

    @pytest.mark.parametrize("key", sorted(PROCESS_SCOPE_KEYS))
    def test_every_listed_key_is_dropped(self, config: Config, tmp_path: Path, key: str) -> None:
        merged = config.merge_agent_settings("orders", fragment(tmp_path, "orders", f'{key} = "value"\nmodel_name = "kept"\n'))

        assert merged == ("model_name",)

    def test_a_deployment_identity_key_is_dropped_too(self, config: Config, tmp_path: Path) -> None:
        """C6 makes these unreadable, so a fragment declaring one is writing into a wall."""
        merged = config.merge_agent_settings("orders", fragment(tmp_path, "orders", 'blueprint_group = "finance"\n'))

        assert merged == ()


class TestAFileThatIsNotThere:
    def test_an_agent_need_not_ship_one(self, config: Config, tmp_path: Path) -> None:
        assert config.merge_agent_settings("orders", tmp_path / "pkg" / "orders" / "settings.toml") == ()

    def test_the_processs_own_settings_file_is_not_merged_again(self, config: Config, tmp_path: Path) -> None:
        """An agent declared beside the group's own file would otherwise inherit every root key."""
        assert config.merge_agent_settings("orders", tmp_path / "settings.toml") == ()
        assert config.for_namespace("orders").get("app_name") == "the-process"

    def test_an_empty_file_contributes_nothing(self, config: Config, tmp_path: Path) -> None:
        assert config.merge_agent_settings("orders", fragment(tmp_path, "orders", "")) == ()

    def test_a_broken_file_is_reported_not_skipped(self, config: Config, tmp_path: Path) -> None:
        """A file that is there was meant to be used, so failing to read it is an error."""
        with pytest.raises(ConfigError, match="could not be read"):
            config.merge_agent_settings("orders", fragment(tmp_path, "orders", "this is not = = toml\n"))
