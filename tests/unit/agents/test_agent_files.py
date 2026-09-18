"""An agent's own files, read from the root its entry in the agent map states.

These cases build real directories and import real modules, because both bugs they pin down were
invisible to a test that stated paths instead of creating them:

- the group looked for an agent's ``settings.toml`` beside its *declaration module* -- inside
  ``src/`` -- while every scaffolded project writes it beside ``src/``. The file was simply never
  read, and an agent silently ran on the group's defaults.
- prompts resolved against the *process* working directory, which is one directory for a whole
  group and therefore right for at most one agent. The others found nothing, or found a
  neighbour's prompt of the same name.

Both were failures of inference: a root derived from where the declaration happened to sit is
right for one layout and quietly wrong for the rest. The root is now stated in the map, and these
tests hold it to being stated -- including at a nesting depth no derivation rule would have
guessed.
"""

import sys
import textwrap
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from blueprint.agents.agent.prompt_loader import PromptLoader
from blueprint.agents.agent_group import AgentGroup
from blueprint.agents.component.component import Component
from blueprint.agents.config import Config, ConfigError
from blueprint.agents.group_config import GroupConfig, GroupConfigError

DECLARATION = "from blueprint.agents.app_builder import AppBuilder\nagent = AppBuilder()\n"


@pytest.fixture(autouse=True)
def reset_component_state() -> Generator[None]:
    with patch(
        "blueprint.agents.component.registry.CorrelationContextProvider.get_correlation_context",
        return_value=MagicMock(),
    ):
        yield
    Component.reset_shared_state()


@pytest.fixture
def image(tmp_path: Path) -> Generator[Path]:
    """An image root on ``sys.path``, cleaned up so modules do not leak between tests."""
    sys.path.insert(0, str(tmp_path))
    before = set(sys.modules)
    yield tmp_path.resolve()
    sys.path.remove(str(tmp_path))
    for name in set(sys.modules) - before:
        del sys.modules[name]


def make_agent(image: Path, relative: str, *, prompt: str | None = None, settings: str | None = None) -> Path:
    """Create one agent directory in the shape ``asbs setup`` writes, and return its root."""
    root = image / relative
    (root / "src" / "prompts").mkdir(parents=True)
    (root / "src" / "__init__.py").write_text("", encoding="utf-8")
    (root / "src" / "main.py").write_text(DECLARATION, encoding="utf-8")
    if settings is not None:
        (root / "settings.toml").write_text(settings, encoding="utf-8")
    if prompt is not None:
        (root / "src" / "prompts" / "system.prompt").write_text(prompt, encoding="utf-8")
    return root


def write_map(image: Path, entries: str) -> None:
    (image / "agents.toml").write_text(textwrap.dedent(entries), encoding="utf-8")


def process_config(image: Path) -> Config:
    (image / "settings.toml").write_text(
        '[development]\napp_environment = "development"\napp_name = "the-process"\napp_port = 8000\n',
        encoding="utf-8",
    )
    return Config(settings_files=[str(image / "settings.toml")], root_path=str(image))


def resolve(image: Path, agents: str) -> AgentGroup:
    config = process_config(image)
    return AgentGroup.from_config(GroupConfig.resolve(config, environ={"BLUEPRINT_AGENTS": agents}))


class TestEachAgentReadsItsOwnFiles:
    """Two agents at different depths, neither of which a positional rule would have found."""

    @pytest.fixture
    def two_agents(self, image: Path) -> Path:
        make_agent(image, "agents/some_topic/alpha", prompt="ALPHA PROMPT", settings='model_name = "alpha-model"')
        make_agent(image, "services/beta", prompt="BETA PROMPT", settings='model_name = "beta-model"')
        write_map(
            image,
            """
            [agents.alpha]
            root   = "agents/some_topic/alpha"
            module = "agents.some_topic.alpha.src.main:agent"

            [agents.beta]
            root   = "services/beta"
            module = "services.beta.src.main:agent"
            """,
        )
        return image

    def test_settings_come_from_the_stated_root(self, two_agents: Path) -> None:
        group = resolve(two_agents, "alpha,beta")

        assert group.settings["alpha"] == two_agents / "agents/some_topic/alpha/settings.toml"
        assert group.settings["beta"] == two_agents / "services/beta/settings.toml"

    def test_each_agent_reads_its_own_settings(self, two_agents: Path) -> None:
        config = process_config(two_agents)
        group = AgentGroup.from_config(GroupConfig.resolve(config, environ={"BLUEPRINT_AGENTS": "alpha,beta"}))
        group.assemble(config)

        assert config.for_namespace("alpha").get("model_name") == "alpha-model"
        assert config.for_namespace("beta").get("model_name") == "beta-model"

    def test_each_agent_resolves_its_own_prompt(self, two_agents: Path) -> None:
        """The failure this prevents is a prompt that resolves to the neighbour's file."""
        config = process_config(two_agents)
        group = AgentGroup.from_config(GroupConfig.resolve(config, environ={"BLUEPRINT_AGENTS": "alpha,beta"}))
        group.assemble(config)

        assert PromptLoader.load_prompt("system", config.for_namespace("alpha")) == "ALPHA PROMPT"
        assert PromptLoader.load_prompt("system", config.for_namespace("beta")) == "BETA PROMPT"

    def test_the_package_root_each_agent_sees_is_its_own(self, two_agents: Path) -> None:
        config = process_config(two_agents)
        AgentGroup.from_config(GroupConfig.resolve(config, environ={"BLUEPRINT_AGENTS": "alpha,beta"})).assemble(config)

        assert config.for_namespace("alpha").get_package_root() == two_agents / "agents/some_topic/alpha"
        assert config.for_namespace("beta").get_package_root() == two_agents / "services/beta"


class TestAStandaloneAgentIsNotAGroupOfOne:
    """An agent served on its own has no map, so nothing can sit at its root claiming otherwise.

    A group of one is still a group. Requiring an agent to declare itself one in order to run
    alone put the group's own file inside the agent -- which is the thing an agent must never
    carry, because carrying it is knowing whether it is running alone. Standalone is served by
    the declaration's own ``create_app`` factory instead, and this rule needs no exception.
    """

    def test_an_agent_mapped_at_the_image_root_is_refused(self, image: Path) -> None:
        """The old group-of-one shape: the agent flattened into the image, map beside it."""
        (image / "src" / "prompts").mkdir(parents=True)
        (image / "src" / "__init__.py").write_text("", encoding="utf-8")
        (image / "src" / "main.py").write_text(DECLARATION, encoding="utf-8")
        write_map(
            image,
            """
            [agents.solo]
            root   = "."
            module = "src.main:agent"
            """,
        )

        with pytest.raises(GroupConfigError, match="belongs to the image"):
            resolve(image, "solo")


class TestTheMapStatesTheRoot:
    """``root`` is required, and wrong values are refused rather than worked around."""

    def test_a_missing_root_is_refused(self, image: Path) -> None:
        make_agent(image, "alpha")
        write_map(
            image,
            """
            [agents.alpha]
            module = "alpha.src.main:agent"
            """,
        )

        with pytest.raises(GroupConfigError, match="has no 'root'"):
            resolve(image, "alpha")

    def test_a_root_that_is_not_there_is_refused(self, image: Path) -> None:
        write_map(
            image,
            """
            [agents.alpha]
            root   = "nowhere"
            module = "alpha.src.main:agent"
            """,
        )

        with pytest.raises(GroupConfigError, match="is not a directory"):
            resolve(image, "alpha")

    def test_a_root_outside_the_image_is_refused(self, image: Path) -> None:
        write_map(
            image,
            """
            [agents.alpha]
            root   = "../elsewhere"
            module = "alpha.src.main:agent"
            """,
        )

        with pytest.raises(GroupConfigError, match="outside the image root"):
            resolve(image, "alpha")

    def test_two_agents_sharing_a_root_are_refused(self, image: Path) -> None:
        """They would read one another's settings and prompts."""
        make_agent(image, "shared")
        write_map(
            image,
            """
            [agents.alpha]
            root   = "shared"
            module = "shared.src.main:agent"

            [agents.beta]
            root   = "shared"
            module = "shared.src.main:agent"
            """,
        )

        with pytest.raises(GroupConfigError, match="share the root"):
            resolve(image, "alpha,beta")


class TestMisplacedFilesAreRefused:
    """A file the framework will not read is refused, never ignored.

    Ignoring it is what the original defect did: the settings file was there, looked correct, and
    was never opened -- so the agent ran on the group's defaults and nothing said so.
    """

    def test_settings_inside_src_is_refused(self, image: Path) -> None:
        root = make_agent(image, "alpha", prompt="P")
        (root / "src" / "settings.toml").write_text('model_name = "wrong-place"', encoding="utf-8")
        write_map(
            image,
            """
            [agents.alpha]
            root   = "alpha"
            module = "alpha.src.main:agent"
            """,
        )

        with pytest.raises(GroupConfigError, match="settings.toml"):
            resolve(image, "alpha")

    def test_an_agent_map_inside_a_grouped_agent_is_refused(self, image: Path) -> None:
        root = make_agent(image, "alpha", prompt="P")
        (root / "agents.toml").write_text('[agents.alpha]\nroot = "."\nmodule = "src.main:agent"\n', encoding="utf-8")
        write_map(
            image,
            """
            [agents.alpha]
            root   = "alpha"
            module = "alpha.src.main:agent"
            """,
        )

        with pytest.raises(GroupConfigError, match="belongs to the image"):
            resolve(image, "alpha")


class TestAFragmentNeverNamesItsOwnAgent:
    """An agent's settings file becomes that agent's scope, so it must not scope keys itself.

    Found in a real migration: a project whose settings.toml already carried
    ``[default.risk_identifier]`` merged without complaint, nested every key to
    ``risk_identifier.risk_identifier.*``, and surfaced much later as "No model name for
    runtime agent 'risk_identifier_agent' configured" -- a message naming the agent and not
    the file that caused it.
    """

    def test_a_section_named_after_the_agent_is_refused(self, tmp_path: Path) -> None:
        config = process_config(tmp_path)
        fragment = tmp_path / "agent.toml"
        fragment.write_text('[default.orders]\nmodel_name = "m"\n\n', encoding="utf-8")

        with pytest.raises(ConfigError, match="its own name"):
            config.merge_agent_settings("orders", fragment)

    def test_the_unprefixed_form_serves_both_shapes(self, tmp_path: Path) -> None:
        """Plain [default] is the fix, and it resolves standalone too."""
        config = process_config(tmp_path)
        fragment = tmp_path / "agent.toml"
        fragment.write_text('[default]\nmodel_name = "m"\n\n', encoding="utf-8")

        config.merge_agent_settings("orders", fragment)

        assert config.for_namespace("orders").get("model_name") == "m"

    def test_a_table_that_is_not_the_agents_name_is_left_alone(self, tmp_path: Path) -> None:
        """[cache] is this agent's cache configuration, not a scope."""
        config = process_config(tmp_path)
        fragment = tmp_path / "agent.toml"
        fragment.write_text('[default]\nmodel_name = "m"\n\n[cache]\nbackend = "disk"\n\n', encoding="utf-8")

        config.merge_agent_settings("orders", fragment)

        assert config.for_namespace("orders").get("model_name") == "m"
