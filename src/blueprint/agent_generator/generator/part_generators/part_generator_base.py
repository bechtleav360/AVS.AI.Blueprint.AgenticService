import os
import re
from pathlib import Path
from typing import Any


class PartGeneratorBase:
    """Base class for generating files from templates based on a configuration."""

    def __init__(self, config: dict[str, Any], template_dir: str | Path, src_path: str) -> None:
        """
        Args:
            config: Configuration dictionary.
            template_dir: Directory containing the template files.
            src_path: Path in the scr directory, where the generated files will be created.
        """

        self.config = config

        if not Path(template_dir).exists():
            raise FileNotFoundError(f"Template directory not found: {template_dir}")
        self.template_dir = template_dir
        self.template_vars: dict[str, str] = {}

        self.src_path = src_path
        self.template_file_name: str | None = None

    def to_py_file_name(self) -> str:
        """Converts a file name to a corresponding Python file name."""
        if self.template_file_name is None:
            raise RuntimeError("template_file_name is not set")
        return f"{self.template_file_name.split('.')[0]}.py"

    @staticmethod
    def to_class_name(name: str) -> str:
        """Convert any string to a valid UpperCamelCase Python class name.

        Splits on non-alphanumeric characters and capitalizes each part.
        Example: 'my-cool-agent' -> 'MyCoolAgent'
        """
        parts = re.split(r"[^a-zA-Z0-9]", name)
        return "".join(part[0].upper() + part[1:] if part else "" for part in parts if part)

    @staticmethod
    def camel_to_snake(name: str) -> str:
        """
        Convert a CamelCase class name to snake_case variable name.
        Handles acronyms better by treating sequences of 2+ uppercase letters as a single word.
        """

        # Handle the case of multiple uppercase letters (acronyms) followed by lowercase
        s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
        # Handle the case of a lowercase letter or number followed by an uppercase letter
        s2 = re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1)
        # Handle the case of multiple uppercase letters at the end of the string
        s3 = re.sub("([A-Z])([A-Z][a-z])", r"\1_\2", s2)
        return s3.lower()

    def create_file(self, output_path: str = "") -> None:
        """Create a file from a template.

        Args:
            output_path: Path to the output file.
        """

        if self.template_file_name is None:
            template = "\n".join(template_var for template_var in self.template_vars.values())
        else:
            full_path = os.path.join(self.template_dir, self.src_path, self.template_file_name)
            with open(full_path) as f:
                template = f.read()

            try:
                for key, value in self.template_vars.items():
                    template = template.replace(key, value)
            except Exception as e:
                raise ValueError(f"Error processing template {full_path}: {e}") from e

        out_path = Path(output_path).joinpath(self.src_path).resolve().joinpath(self.to_py_file_name())
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            f.write(template)

    def get_output_filename(self, component_type: str) -> str:
        """Get output filename with component_name prefix if available.

        Args:
            component_type: Type of component (e.g., 'handler', 'service', 'api', 'scheduler')

        Returns:
            Filename with component_name prefix, e.g., 'order_validation_handler.py'
        """
        component_name = self.config.get("component_name", "")
        if not component_name:
            # Fallback to existing filename generation method
            return self.to_py_file_name()

        # Convert component_name to snake_case
        snake_name = self.camel_to_snake(component_name)
        return f"{snake_name}_{component_type}.py"
