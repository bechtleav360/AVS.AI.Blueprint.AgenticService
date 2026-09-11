from pathlib import Path
from typing import Any

from .part_generator_base import PartGeneratorBase


class MainPartGenerator(PartGeneratorBase):
    """Generate main.py for the agents blueprint.

    What it writes is a declaration and nothing else: ``agent = AppBuilder()...`` with no
    configuration, no ``build()`` and no module-level ``app``. The declaration is the unit the
    framework hosts -- ``agents.toml`` points at this module's ``agent`` attribute, and
    ``python -m blueprint.agents.entrypoint`` builds it under the namespace the deployment's
    group gives it.

    Two consequences are deliberate and are why this generator changed shape:

    - **Classes, not instances.** ``with_service(OrderService)`` rather than
      ``with_service(OrderService())``. A component constructed on the ``with_*`` line is
      constructed before any namespace exists, so it belongs to the root for ever; a group
      refuses an already-built instance for that reason. The class form is built by ``build()``
      inside the agent's own scope and works in both shapes.
    - **An unbuilt ``AgentBuilder``.** ``with_agent`` hands it ``config.for_namespace(<agent>)``
      at build time, so the model and prompt come from this agent's own configuration view
      rather than from whatever configuration happened to be in scope where the chain was
      written.
    """

    def __init__(self, config: dict[str, Any], template_dir: str | Path, src_path: str) -> None:
        super().__init__(config, template_dir, src_path)
        self.template_file_name = "main.txt"
        self.template_vars["app_name"] = self.config["name"]
        self.template_vars["app_description"] = self.config["description"]
        self.template_vars["imports"] = self._generate_main_imports()
        self.template_vars["agent_declaration"] = self._generate_agent_declaration()

    def _generate_main_imports(self) -> str:
        """Generate import statements for main.py."""

        lines = []
        if self.config["agent_layer"]:
            lines.append("from blueprint.agents.agent import AgentBuilder")
        lines.append("from blueprint.agents.app_builder import AppBuilder")

        lines.append("")

        if self.config["communication_layer"].get("rest_api", {}).get("add_rest_api", False):
            lines.append(f"from .api import {self.config['communication_layer']['rest_api']['name']}")

        if "handlers" in self.config["communication_layer"]:
            lines.append(f"from .handlers import {', '.join(h for h in self.config['communication_layer']['handlers'])}")

        if len(self.config["service_layer"]) < 4:
            lines.append(f"from .services import {', '.join(s for s in self.config['service_layer'])}")
        else:
            lines.append("from .services import (")
            for service_name in self.config["service_layer"]:
                lines.append(f"    {service_name},")
            lines[-1] = lines[-1][:-1]
            lines.append(")")

        return "\n".join(lines)

    def _generate_agent_declaration(self) -> str:
        """Generate the agent runtimes and the ``agent = AppBuilder()...`` declaration.

        Each runtime is declared as a module-level ``AgentBuilder`` rather than inline, so that
        every line of the chain is one registration. That is what ``asbs create`` needs: it
        rewrites the chain line by line to keep it in dependency order, and a registration
        spanning several lines would lose its continuation lines on the next ``asbs create``.
        The same shape is what ``asbs create agent`` writes, so a generated project and one
        grown with the CLI stay identical.

        The chain is emitted in ``sort_components`` order -- services, agents, handlers, REST
        APIs -- for the same reason: the first ``asbs create`` would otherwise reorder
        everything and make its diff unreadable.
        """

        lines: list[str] = []

        for agent in self.config["agent_layer"].values():
            runtime_name = agent["runtime_name"]
            lines.extend(
                [
                    f"{runtime_name} = (",
                    f'    AgentBuilder(runtime_name="{runtime_name}")',
                    "    .with_model_from_config()",
                    f'    .with_system_prompt("{runtime_name}_system")',
                    ")",
                    "",
                ]
            )

        lines.extend(["agent = (", "    AppBuilder()"])

        for service_name in self.config["service_layer"]:
            lines.append(f"    .with_service({service_name})")

        for agent in self.config["agent_layer"].values():
            # The name is given to with_agent rather than to AgentBuilder.build(): it is the
            # registry key the services resolve the runtime by, and AppBuilder qualifies it with
            # the agent's namespace so two agents' runtimes cannot collide on it.
            lines.append(f'    .with_agent({agent["runtime_name"]}, name="{agent["runtime_name"]}")')

        if "handlers" in self.config["communication_layer"]:
            for handler_name in self.config["communication_layer"]["handlers"]:
                lines.append(f"    .with_handler({handler_name})")

        if self.config["communication_layer"].get("rest_api", {}).get("add_rest_api", False):
            lines.append(f"    .with_rest_api({self.config['communication_layer']['rest_api']['name']})")

        lines.append(")")

        return "\n".join(lines)
