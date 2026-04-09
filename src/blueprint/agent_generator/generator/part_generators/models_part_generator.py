from pathlib import Path
from typing import Any

from .part_generator_base import PartGeneratorBase


class ModelPartGenerator(PartGeneratorBase):
    def __init__(self, config: dict[str, Any], template_dir: str | Path, src_path: str) -> None:
        super().__init__(config, template_dir, src_path)
        self.template_file_name = "dto.txt"

    def get_models_subfolder(self) -> str:
        """Get models subfolder based on component_name, or empty string."""
        component_name = self.config.get("component_name", "")
        if component_name:
            return self.camel_to_snake(component_name)
        return ""

    def to_py_file_name(self) -> str:
        """Include subfolder in filename when component_name is set."""
        base_name = super().to_py_file_name()
        subfolder = self.get_models_subfolder()
        if subfolder:
            return f"{subfolder}/{base_name}"
        return base_name

    @staticmethod
    def _generate_model_classes(model_classes: dict[str, Any]) -> str:
        """Generate the model classes based on the configuration and the template file.

        Args:
            model_classes: A dictionary containing the model classes.

        Returns:
            A string containing the generated model classes.
        """
        lines = []

        for model_class_name, model in model_classes.items():
            lines.extend([f"class {model_class_name}(BaseModel):", '    """', f"    {model['description']}", '    """'])
            for field_name, field in model["fields"].items():
                lines.append(
                    f"    {field_name}: {field['type']} = Field("
                    + ("..., " if not field.get("default", None) else "")
                    + f"description='{field['description']}'"
                    + (f", default=\"{field.get('default', None)}\")" if field.get("default", None) else ")")
                )
            lines.append("")

        return "\n".join(lines)


class DTOPartGenerator(ModelPartGenerator):
    def __init__(self, config: dict[str, Any], template_dir: str | Path, src_path: str) -> None:
        super().__init__(config, template_dir, src_path)
        self.template_file_name = "dto.txt"
        self.template_vars["dto_classes"] = self._generate_model_classes(self.config["communication_layer"]["rest_api"]["dto_classes"])


class DomainModelPartGenerator(ModelPartGenerator):
    def __init__(self, config: dict[str, Any], template_dir: str | Path, src_path: str) -> None:
        super().__init__(config, template_dir, src_path)
        self.template_file_name = "domain_models.txt"
        self.template_vars["domain_model_classes"] = self._generate_model_classes(self.config["domain_models"])


class MapperPartGenerator(ModelPartGenerator):
    def __init__(self, config: dict[str, Any], template_dir: str | Path, src_path: str) -> None:
        super().__init__(config, template_dir, src_path)
        self.template_file_name = "mapper.txt"
        self.template_vars["imports"] = self._create_mapper_imports()
        self.template_vars["mapper_class"] = self._generate_mapper_class()

    def _create_mapper_imports(self) -> str:
        """
        Generate import statements for the mapper class based on the configuration.

        Returns:
            A string containing the import statements.
        """

        dto_classes = []
        domain_model_classes = []
        for mapping in self.config["communication_layer"]["rest_api"]["mapper"]["mappings"]:
            if mapping["from"]["type"] == "dto" and mapping["from"]["name"] not in dto_classes:
                dto_classes.append(mapping["from"]["name"])
            elif mapping["from"]["name"] not in domain_model_classes:
                domain_model_classes.append(mapping["from"]["name"])
            if mapping["to"]["type"] == "dto" and mapping["to"]["name"] not in dto_classes:
                dto_classes.append(mapping["to"]["name"])
            elif mapping["to"]["name"] not in domain_model_classes:
                domain_model_classes.append(mapping["to"]["name"])

        lines = []
        if len(dto_classes) < 4:
            lines.append(f"from .dto import {', '.join(dto_classes)}")
        else:
            lines.append("from .dto import (")
            for dto_class_name in dto_classes:
                lines.append(f"    {dto_class_name},")
            lines[-1] = lines[-1][:-1]
            lines.append(")")

        if len(domain_model_classes) < 4:
            lines.append(f"from .domain_models import {', '.join(domain_model_classes)}")
        else:
            lines.append("from .domain_models import (")
            for domain_model_class_name in domain_model_classes:
                lines.append(f"    {domain_model_class_name},")
            lines[-1] = lines[-1][:-1]
            lines.append(")")

        return "\n".join(lines)

    def _generate_mapper_class(self) -> str:
        """
        Generate the mapper class based on the configuration and the template file.

        Returns:
            A string containing the generated mapper class.
        """

        lines = [
            f"class {self.config['communication_layer']['rest_api']['mapper']['name']}:",
            '    """Static mapper class for converting between domain models and DTOs."""',
            "",
        ]

        for mapping in self.config["communication_layer"]["rest_api"]["mapper"]["mappings"]:
            lines.extend(
                [
                    "    @staticmethod",
                    (
                        f"    def from_{self.camel_to_snake(mapping['from']['name'])}("
                        if mapping["from"]["type"] == "dto"
                        else f"    def to_{self.camel_to_snake(mapping['to']['name'])}("
                    )
                    + f"{self.camel_to_snake(mapping['from']['name'])}: "
                    + f"{mapping['from']['name']}) -> {mapping['to']['name']}:",
                    f"        return {mapping['to']['name']}(",
                    *[
                        f"            {_in}={self.camel_to_snake(mapping['from']['name'])}.{out},"
                        for _in, out in mapping["field_mappings"].items()
                    ],
                ]
            )
            lines[-1] = lines[-1][:-1]
            lines.append("        )")
            lines.append("")

        return "\n".join(lines)
