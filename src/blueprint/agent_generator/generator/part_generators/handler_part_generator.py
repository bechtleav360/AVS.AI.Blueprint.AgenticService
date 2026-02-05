from pathlib import Path

from .part_generator_base import PartGeneratorBase


class HandlerPartGenerator(PartGeneratorBase):
    def __init__(self, config: dict, template_dir: str | Path, src_path: str, handler_name: str) -> None:
        super().__init__(config, template_dir, src_path)
        self.template_file_name = "handler.txt"
        self.handler_name = handler_name

        self.template_vars["imports"] = self._create_handler_imports()
        self.template_vars["handler_class"] = self._generate_handler_class()
        self.template_vars["on_startup"] = self._generate_on_startup()

    def _create_handler_imports(self) -> str:
        """
        Generate import statements for the handler class based on the configuration.

        Returns:
            A string containing the import statements.
        """

        lines = []
        for service in self.config["communication_layer"]["handlers"][self.handler_name]["uses_services"]:
            lines.append(f"from ..services import {service}")
        return "\n".join(lines)

    def _generate_handler_class(self) -> str:
        """
        Generate the handler class based on the configuration and the template file.

        Returns:
            A string containing the generated handler class.
        """

        lines = [
            f"class {self.handler_name}(EventHandler):",
            '    """',
            f"    {self.config['communication_layer']['handlers'][self.handler_name]['description']}",
            '    """',
            "",
            f"    def __init__(self, name: str = \"{self.camel_to_snake(self.handler_name)}\") -> None:",
            f"        super().__init__(name=name, "
            f"priority={self.config['communication_layer']['handlers'][self.handler_name]['priority']})",
            "        self._input_event_type: str = \"\"",
            *[f"        self.{self.camel_to_snake(service)}: {service} | None = None"
             for service in self.config["communication_layer"]["handlers"][self.handler_name]["uses_services"]],
        ]

        return "\n".join(lines)

    def _generate_on_startup(self) -> str:
        """
        Generate the on_startup method for the handler class based on the configuration.

        Returns:
            A string containing the generated on_startup method.
        """

        lines = [
            "    async def on_startup(self) -> None:",
            '        """Initialize the handler by getting services from the registry."""',
            ""
        ]
        for service in self.config["communication_layer"]["handlers"][self.handler_name]["uses_services"]:
            lines.append(
                f"        self.{self.camel_to_snake(service)} = "
                f"self.get_registry().get_service('{self.camel_to_snake(service)}')"
            )
        lines.extend([
            "",
            f"        self._input_event_type = self.get_config().get(\"{self.camel_to_snake(self.handler_name)}\""
            ", {}).get(\"input_event_type\", "")",
            "        if self._input_event_type == \"\":",
            "            raise ValueError(\"input_event_type is not set in config\")"
        ])

        return "\n".join(lines)
