from pathlib import Path

from .part_generator_base import PartGeneratorBase


class CopyPartGenerator(PartGeneratorBase):
    def __init__(self, config: dict, template_dir: str | Path, src_path: str, template_file_name: str, output_file_name: str) -> None:
        super().__init__(config, template_dir, src_path)
        self.template_file_name = template_file_name
        self.output_file_name = output_file_name

    def to_py_file_name(self) -> str:
        """Converts a file name to a corresponding Python file name."""
        return self.output_file_name
