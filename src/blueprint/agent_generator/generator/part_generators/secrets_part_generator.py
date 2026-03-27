from pathlib import Path

from .part_generator_base import PartGeneratorBase


class SecretsPartGenerator(PartGeneratorBase):
    def __init__(self, config: dict, template_dir: str | Path, src_path: str) -> None:
        super().__init__(config, template_dir, src_path)
        self.template_file_name = None
        self.template_vars["content"] = self._create_secrets_content()

    def to_py_file_name(self) -> str:
        return "secrets.toml"

    def _create_secrets_content(self) -> str:
        return '[default]\nmodel_api_key = "Your-API-Key"\n'
