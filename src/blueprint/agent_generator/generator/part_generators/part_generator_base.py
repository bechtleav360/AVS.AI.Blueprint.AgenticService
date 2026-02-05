import os
import re
from pathlib import Path


class PartGeneratorBase:
    """Base class for generating files from templates based on a configuration.
    """

    def __init__(self, config: dict, template_dir: str | Path, src_path: str) -> None:
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
        self.template_vars: dict = {}

        self.src_path = src_path
        self.template_file_name: str | None = None

    def to_py_file_name(self) -> str:
        """Converts a file name to a corresponding Python file name."""

        return f"{self.template_file_name.split('.')[0]}.py"

    @staticmethod
    def camel_to_snake(name: str) -> str:
        """
        Convert a CamelCase class name to snake_case variable name.
        Handles acronyms better by treating sequences of 2+ uppercase letters as a single word.
        """

        # Handle the case of multiple uppercase letters (acronyms) followed by lowercase
        s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
        # Handle the case of a lowercase letter or number followed by an uppercase letter
        s2 = re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1)
        # Handle the case of multiple uppercase letters at the end of the string
        s3 = re.sub('([A-Z])([A-Z][a-z])', r'\1_\2', s2)
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
            with open(full_path, 'r') as f:
                template = f.read()

            try:
                for key, value in self.template_vars.items():
                    template = template.replace(key, value)
            except Exception as e:
                raise ValueError(f"Error processing template {full_path}: {e}")

        output_path = Path(output_path).joinpath(self.src_path).resolve().joinpath(self.to_py_file_name())
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path , 'w') as f:
            f.write(template)
