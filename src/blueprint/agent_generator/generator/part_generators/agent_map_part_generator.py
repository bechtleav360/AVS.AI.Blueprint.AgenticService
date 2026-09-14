from pathlib import Path
from typing import Any

from blueprint.agents.component.namespace import validate_namespace

from .part_generator_base import PartGeneratorBase


class AgentMapPartGenerator(PartGeneratorBase):
    """Generate ``agents.toml``, the map from agent name to declaration.

    The framework resolves an agent name to code through this file and through nothing else --
    there is no discovery by convention, because a set of agents that depends on what happens
    to be importable makes a renamed directory a silently removed agent. So a project that
    does not ship one cannot be hosted by ``python -m blueprint.agents.entrypoint`` at all.

    The name is validated here rather than repaired. It becomes a namespace, and from there a
    queue group, a durable name, a cache partition and a telemetry ``service.name``; a name
    quietly rewritten to fit would be four different names for one agent. Refusing it at
    scaffolding time is the one moment it is still free to change.
    """

    def __init__(self, config: dict[str, Any], template_dir: str | Path, src_path: str) -> None:
        super().__init__(config, template_dir, src_path)
        self.template_file_name = "agents_toml.txt"
        self.template_vars["agent_namespace"] = self.agent_namespace(config)

    @classmethod
    def agent_namespace(cls, config: dict[str, Any]) -> str:
        """Return the namespace this project's agent is deployed under.

        The project name in snake case. Derived rather than asked for, because a project that
        has exactly one agent has no second name to give it -- and the derivation is visible in
        the generated file, which is where it can be changed before the first deploy.

        Raises:
            ValueError: if the project name does not survive the derivation as a legal
                namespace -- a leading digit, for instance. The generator fails rather than
                writing a project that cannot start.
        """
        namespace = cls.camel_to_snake(config["name"])
        try:
            return validate_namespace(namespace)
        except ValueError as exc:
            raise ValueError(
                f"Project name '{config['name']}' gives the agent namespace '{namespace}', which cannot be used: "
                f"{exc} Choose a project name whose snake_case form matches [a-z][a-z0-9_]*."
            ) from exc

    def to_py_file_name(self) -> str:
        """The agent map is TOML, and lives at the project root."""
        return "agents.toml"
