from pathlib import Path

from .part_generator_base import PartGeneratorBase


class ServicePartGenerator(PartGeneratorBase):
    def __init__(self, config: dict, template_dir: str | Path, src_path: str, service_name: str) -> None:
        super().__init__(config, template_dir, src_path)
        self.template_file_name = "service.txt"
        self.service_name = service_name

        self.template_vars["service_description"] = self.config["service_layer"][service_name]["description"]
        self.template_vars["imports"] = self._create_service_imports()
        self.template_vars["class_initialization"] = self._generate_class_initialization()
        self.template_vars["on_startup"] = self._generate_on_startup()
        self.template_vars["process_functions"] = self._generate_process_function()

    def to_py_file_name(self) -> str:
        """Converts a file name to a corresponding Python file name."""
        return f"{self.camel_to_snake(self.service_name)}.py"

    def _create_service_imports(self) -> str:
        """
        Generate import statements for service.py.
        """

        lines = []
        if self.config["service_layer"][self.service_name]["uses_domain_models"]:
            if len(self.config["service_layer"][self.service_name]["uses_domain_models"]) < 4:
                lines.append(f"from ..models.domain_models import {', '.join(self.config['service_layer'][self.service_name]['uses_domain_models'])}")
            else:
                lines.append("from ..models.domain_models import (")
                for domain_model_name in self.config["service_layer"][self.service_name]["uses_domain_models"]:
                    lines.append(f"    {domain_model_name},")
                lines[-1] = lines[-1][:-1]
                lines.append(")")

        return "\n".join(lines)

    def _generate_class_initialization(self) -> str:
        """
        Generate class initialization code for service.py.
        """

        lines = []
        lines.extend([
            f"class {self.service_name}(BusinessService):",
            '    """',
            f"    Service for {self.config['name']}.",
            '    """',
            f"    def __init__(self, name: str = \"{self.service_name}\") -> None:",
            "        super().__init__(name=name)"
        ])

        if self.config["service_layer"][self.service_name]["uses_agents"]:
            for agent_name in self.config["service_layer"][self.service_name]["uses_agents"]:
                lines.append(f"        self._{self.camel_to_snake(agent_name)}: AgentRuntime | None = None")

        return "\n".join(lines)

    def _generate_on_startup(self) -> str:
        """
        Generate on_startup code for service.py.
        """

        lines = []
        if self.config["service_layer"][self.service_name]["uses_agents"]:
            lines.extend([
                "    async def on_startup(self) -> None:",
                '        """Initialize the service by getting agent from the registry."""',
            ])

            for agent_name in self.config["service_layer"][self.service_name]["uses_agents"]:
                lines.append(f"        self._{self.camel_to_snake(agent_name)} = self.get_registry()"
                             f".get_agent('{self.config['agent_layer'][agent_name]['runtime_name']}')")

        lines.append("")
        return "\n".join(lines)

    def _generate_process_function(self) -> str:
        """
        Generate process functions for service.py.
        """

        lines = []
        function_parameters = self.config["service_layer"][self.service_name]["process_function"]
        lines.append("")
        lines.append(f"    async def {function_parameters['name']}(self, "
                     f"{self.camel_to_snake(function_parameters["input_type"])}"
                     f": {function_parameters['input_type']}) -> {function_parameters['output_type']}:")
        lines.extend([
            '        """This method contains business logic of this microservice.',
            "",
            "        Args:",
            f"            {self.camel_to_snake(function_parameters['input_type'])} "
            f"({function_parameters['input_type']}): The incoming data, parsed into the domain input model.",
            "",
            "        Returns:",
            f"            {function_parameters['output_type']}: "
            f"The processed data parsed into the domain output model.",
            '        """',
            ""
        ])
        lines.append(f"        raise NotImplementedError()")

        return "\n".join(lines)
