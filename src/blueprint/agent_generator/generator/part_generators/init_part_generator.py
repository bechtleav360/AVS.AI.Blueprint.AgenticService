import ast
from pathlib import Path

from .part_generator_base import PartGeneratorBase


class InitPartGenerator(PartGeneratorBase):
    def __init__(self, config: dict, template_dir: str | Path, src_path: str, output_path: str = "") -> None:
        """Generate __init__.py file from template.

        Args:
            config: Configuration dictionary.
            template_dir: Directory containing the template files.
            src_path: Path in the scr directory, where the generated files will be created.
            output_path: Base Path to the directory.
        """
        super().__init__(config, template_dir, src_path)
        self.template_file_name = None
        self.template_vars = {"content": self.generate_init_content(output_path)}

    def to_py_file_name(self) -> str:
        """Converts a file name to a corresponding Python file name."""
        return "__init__.py"

    @staticmethod
    def get_classes_from_file(file_path: str) -> list[str]:
        """Extract class names from a Python file using AST.

        Args:
            file_path: Path to the Python file.

        Returns:
            List of class names in the file.
        """

        with open(file_path, "r", encoding="utf-8") as f:
            try:
                tree = ast.parse(f.read(), filename=str(file_path))
                return [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
            except (SyntaxError, UnicodeDecodeError):
                return []

    def generate_init_content(self, output_path: str) -> str:
        """Generate __init__.py content with imports and __all__ for all Python files in directory.

        Args:
            output_path: Base Path to the directory.

        Returns:
            Generated __init__.py content.
        """

        directory = Path(output_path).joinpath(self.src_path).resolve()

        if not directory.exists() or not directory.is_dir():
            return ""

        # Get all Python files in the directory (non-recursive)
        py_files = [f for f in directory.glob("*.py") if f.name != "__init__.py"]

        # For each file, get its classes
        imports: dict[str, list[str]] = {}
        for py_file in py_files:
            classes = self.get_classes_from_file(py_file)
            if classes:
                module_name = py_file.stem
                imports[module_name] = classes

        # Generate import statements
        lines = []
        for module, classes in imports.items():
            if classes:
                classes_str = ", ".join(classes)
                lines.append(f"from .{module} import {classes_str}")

        # Generate __all__
        if imports:
            all_classes = [cls for classes in imports.values() for cls in classes]
            lines.append("")
            lines.append("")
            if len(all_classes) < 4:
                lines.append(f"__all__ = {all_classes!r}")
            else:
                lines.append("__all__ = (")
                for cls in all_classes:
                    lines.append(f"    {cls!r},")
                lines[-1] = lines[-1][:-1]
                lines.append(")")

        return "\n".join(lines)
