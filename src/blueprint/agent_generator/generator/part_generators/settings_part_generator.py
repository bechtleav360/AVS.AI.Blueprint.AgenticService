from pathlib import Path

from .part_generator_base import PartGeneratorBase


class SettingsPartGenerator(PartGeneratorBase):
    def __init__(self, config: dict, template_dir: str | Path, src_path: str) -> None:
        super().__init__(config, template_dir, src_path)
        self.template_file_name = "settings.txt"
        self.template_vars["app_name"] = f"app_name = \"{self.config['name']}\""
        self.template_vars["app_description"] = f"app_description = \"{self.config['description']}\""
        self.template_vars["agent_runtime_configs"] = self._create_agent_runtime_configs()

    def to_py_file_name(self) -> str:
        """Converts a file name to a corresponding Python file name."""
        return "settings.toml"

    def _create_agent_runtime_configs(self) -> str:
        """
        Create the agent runtime configs for the settings.toml file.
        """

        lines = []
        for agent_name, agent_config in self.config["agent_layer"].items():
            lines.extend(
                [
                    f"[default.runtimes.{self.camel_to_snake(agent_name)}]",
                    'model_provider = "openai"',
                    'model_name = "gpt-4.1-nano"',
                    "model_max_tokens = 2000",
                    "model_temperature = 0.7",
                    'prompt_directory = "src/prompts"',
                    f'system_prompt_name = "{self.camel_to_snake(agent_name)}_system"',
                    "",
                    f"[default.runtimes.{self.camel_to_snake(agent_name)}.model_settings]",
                    'openai_reasoning_effort = "low"',
                    'openai_reasoning_summary = "detailed"',
                ]
            )

        return "\n".join(lines)
