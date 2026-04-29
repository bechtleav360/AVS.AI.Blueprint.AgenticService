from pathlib import Path
from typing import Any

from .part_generator_base import PartGeneratorBase


class MainPartGenerator(PartGeneratorBase):
    """Generate main.py for the agents blueprint."""

    def __init__(self, config: dict[str, Any], template_dir: str | Path, src_path: str) -> None:
        super().__init__(config, template_dir, src_path)
        self.template_file_name = "main.txt"
        self.template_vars["app_name"] = self.config["name"]
        self.template_vars["app_description"] = self.config["description"]
        self.template_vars["imports"] = self._generate_main_imports()
        self.template_vars["agents_and_app_initialization"] = self._generate_agents_and_app_initialization()

    def _generate_main_imports(self) -> str:
        """Generate import statements for main.py."""

        lines = []
        if self.config["agent_layer"]:
            lines.append("from blueprint.agents.agent import AgentBuilder")
        lines.append("from blueprint.agents.app_builder import AppBuilder")
        if self.config["agent_layer"]:
            lines.append("from blueprint.agents.agent import AgentRuntime")

        lines.extend(["from blueprint.agents.config import Config", ""])

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

    def _generate_agents_and_app_initialization(self) -> str:
        """Generate app initialization code for main.py."""

        lines = []
        if self.config["agent_layer"]:
            lines.append("# Initialize agents")

        for agent_name, agent in self.config["agent_layer"].items():
            lines.extend(
                [
                    f"{agent['runtime_name']}: AgentRuntime = (",
                    f'    AgentBuilder(config, runtime_name="{agent["runtime_name"]}")',
                    "    .with_model_from_config()",
                    f'    .with_system_prompt("{self.camel_to_snake(agent_name)}_system")',
                    f'    .build(name="{self.camel_to_snake(agent_name)}")',
                    ")",
                    "",
                ]
            )

        # Build the application
        lines.extend(["# Build the application", "app = (", "    AppBuilder(config=config)"])

        # Add agents
        for agent in self.config["agent_layer"]:
            lines.append(f"    .with_agent({self.config['agent_layer'][agent]['runtime_name']})")

        # Add services
        for service_name in self.config["service_layer"]:
            lines.append(f"    .with_service({service_name}())")

        # Add handlers
        if "handlers" in self.config["communication_layer"]:
            for handler_name in self.config["communication_layer"]["handlers"]:
                lines.append(f"    .with_handler({handler_name}())")

        # Add REST API if needed
        if self.config["communication_layer"].get("rest_api", {}).get("add_rest_api", False):
            lines.append(f"    .with_rest_api({self.config['communication_layer']['rest_api']['name']}())")

        lines.append("    .build()")
        lines.append(")")

        return "\n".join(lines)
