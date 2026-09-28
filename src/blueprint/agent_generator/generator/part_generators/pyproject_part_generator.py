from pathlib import Path
from typing import Any

from .part_generator_base import PartGeneratorBase


class PyprojectPartGenerator(PartGeneratorBase):
    """Write the ``pyproject.toml`` that makes a scaffolded project installable and testable.

    ``asbs setup`` printed *"Install dependencies: pip install -e ."* as its next step and wrote
    no ``pyproject.toml``, so that command could not work; ``asbs validate`` then reported the
    file as missing on a project the same tool had just produced. Both were true, and the missing
    file is the one thing that fixes them together.

    It declares the framework as the only dependency and ``pytest`` as the only development one,
    because everything else a project needs is a decision its author has not made yet. The pytest
    configuration is the part worth having by default: ``pythonpath = ["."]`` is what lets the
    generated tests import ``src.main`` the way the entry point does, and without it the first
    ``pytest`` run in a new project fails on an import rather than on anything real.
    """

    def __init__(self, config: dict[str, Any], template_dir: str | Path, src_path: str) -> None:
        super().__init__(config, template_dir, src_path)
        self.template_file_name = None
        self.template_vars["content"] = self._pyproject()

    def to_py_file_name(self) -> str:
        return "pyproject.toml"

    def _pyproject(self) -> str:
        distribution = self.camel_to_snake(self.config["name"]).replace("_", "-")
        return f'''[project]
name = "{distribution}"
version = "0.1.0"
description = "{self.config["description"]}"
requires-python = ">=3.13"
dependencies = [
    "avs-blueprint-agents",
]

[project.optional-dependencies]
dev = [
    "pytest",
    "pytest-asyncio",
]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["src*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
# The generated tests import `src.main`, which is how agents.toml names the declaration and how
# the container's entry point imports it. Without the project root on the path, the first pytest
# run in a new project fails on the import rather than on anything the author wrote.
pythonpath = ["."]
asyncio_mode = "auto"
'''
