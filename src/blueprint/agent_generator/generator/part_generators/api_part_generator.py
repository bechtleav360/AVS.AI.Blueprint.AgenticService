from pathlib import Path
from typing import Any

from .part_generator_base import PartGeneratorBase


class APIPartGenerator(PartGeneratorBase):
    def __init__(self, config: dict[str, Any], template_dir: str | Path, src_path: str) -> None:
        super().__init__(config, template_dir, src_path)
        self.template_file_name = "routes.txt"
        self.template_vars["api_description"] = self.config["communication_layer"]["rest_api"]["description"]
        self.template_vars["imports"] = self._create_api_imports()
        self.template_vars["class_initialization"] = self._generate_class_initialization()
        self.template_vars["on_startup"] = self._generate_on_startup()
        self.template_vars["on_shutdown"] = self._generate_on_shutdown()
        self.template_vars["endpoint_functions"] = self._generate_endpoint_functions()
        self.template_vars["register_routes"] = ""

    def to_py_file_name(self) -> str:
        """Converts a file name to a corresponding Python file name."""
        component_name = self.config.get("component_name", "")
        if component_name:
            return f"{self.camel_to_snake(component_name)}_api.py"
        return "routes.py"

    def _create_api_imports(self) -> str:
        """Generate import statements for routes.py."""
        component_name = self.config.get("component_name", "")
        if component_name:
            model_path = f"..models.{self.camel_to_snake(component_name)}.dto"
        else:
            model_path = "..models"

        lines = []
        model_classes = list(self.config["communication_layer"]["rest_api"]["dto_classes"])
        if len(model_classes) < 4:
            lines.append(f"from {model_path} import {', '.join(model_classes)}")
            lines.append(f"from ..models.{self.camel_to_snake(component_name)}.mapper import {self.config["communication_layer"]["rest_api"]["mapper"]["name"]}")
        else:
            lines.append(f"from {model_path} import (")
            for dto_class in model_classes:
                lines.append(f"    {dto_class},")
            lines[-1] = lines[-1][:-1]
            lines.append(")")
            lines.append(f"from ..models.{self.camel_to_snake(component_name)}.mapper import {self.config['communication_layer']['rest_api']['mapper']['name']}")

        service_classes = list(self.config["communication_layer"]["rest_api"]["uses_services"])
        if len(service_classes) < 4:
            lines.append(f"from ..services import {', '.join(service_classes)}")
        else:
            lines.append("from ..services import (")
            for service_class in service_classes:
                lines.append(f"    {service_class},")
            lines[-1] = lines[-1][:-1]
            lines.append(")")

        return "\n".join(lines)

    def _generate_class_initialization(self) -> str:
        """Generate class initialization code for routes.py."""

        lines = []
        lines.extend(
            [
                f"class {self.config['communication_layer']['rest_api']['name']}(RestApiBase):",
                '    """',
                f"    {self.config["communication_layer"]["rest_api"]["description"]}",
                '    """',
                "    def __init__(self) -> None:",
                "        super().__init__()",
            ]
        )

        service_classes = list(self.config["communication_layer"]["rest_api"]["uses_services"])
        if service_classes:
            for service_class in service_classes:
                lines.append(f"        self._{self.camel_to_snake(service_class)}: {service_class} | None = None")

        return "\n".join(lines)

    def _generate_on_startup(self) -> str:
        """Generate on_startup code for routes.py."""

        lines = []
        lines.extend(
            [
                "    async def on_startup(self) -> None:",
                '        """Initialize the REST API by getting service from the registry."""',
            ]
        )

        service_classes = list(self.config["communication_layer"]["rest_api"]["uses_services"])
        if service_classes:
            for service_class in service_classes:
                lines.append(
                    f"        self._{self.camel_to_snake(service_class)} = "
                    f"self.registry.get_service('{self.camel_to_snake(service_class)}')"
                )

        return "\n".join(lines)

    def _generate_on_shutdown(self) -> str:
        """Generate a no-op on_shutdown method for the REST API class."""
        return "\n".join(
            [
                "    async def on_shutdown(self) -> None:",
                '        """Clean up REST API resources on shutdown."""',
            ]
        )

    def _generate_endpoint_functions(self) -> str:
        """Generate endpoint functions for routes.py."""

        endpoint_functions = self.config["communication_layer"]["rest_api"]["endpoint_functions"]
        lines = []
        for endpoint, endpoint_parameters in endpoint_functions.items():
            method = endpoint_parameters["method"].lower()
            lines.append(
                f"    @RestApiBase.{method}('/{endpoint}', response_model={endpoint_parameters['output_dto']},"
                f" summary='Process a {endpoint} request')"
            )
            lines.append(
                f"    async def {endpoint}(self, "
                f"{self.camel_to_snake(endpoint_parameters['input_dto'])}: "
                f"{endpoint_parameters['input_dto']}) -> "
                f"{endpoint_parameters['output_dto']}:"
            )
            lines.extend(
                [
                    '        """',
                    "        This method should only concern itself with processing the dto. All business logic should be in the service.",
                    "        The service should never be aware of the rest api or the dto class. Instead, use domain specific model classes.",
                    "",
                    "        Args:",
                    f"            {self.camel_to_snake(endpoint_parameters['input_dto'])} "
                    f"({endpoint_parameters['input_dto']}): "
                    f"The incoming data, parsed into the domain input model.",
                    "",
                    "        Returns:",
                    f"            {endpoint_parameters['output_dto']}: " f"The processed data parsed into the domain output model.",
                    '        """',
                    "",
                    "        try:",
                    "            # Use the mapper to convert from the dto to the domain model",
                    f"            input_domain_model = {self.config['communication_layer']['rest_api']['mapper']['name']}."
                    f"from_{self.camel_to_snake(endpoint_parameters['input_dto'])}("
                    f"{self.camel_to_snake(endpoint_parameters['input_dto'])})",
                    "",
                    "            # Use the service to process the request",
                    f"            output_domain_model = await self._{self.camel_to_snake(endpoint_parameters['service'])}."
                    f"{self.config['service_layer'][endpoint_parameters['service']]['process_function']['name']}"
                    "(input_domain_model)",
                    "",
                    "            # Return the response as a dto",
                    f"            return {self.config['communication_layer']['rest_api']['mapper']['name']}."
                    f"to_{self.camel_to_snake(endpoint_parameters['output_dto'])}(output_domain_model)",
                    "        except Exception as e:",
                    "            logger.exception('Unexpected error when processing request')",
                    "            raise HTTPException(status_code=500, detail=str(e))",
                    "",
                ]
            )

        return "\n".join(lines)
