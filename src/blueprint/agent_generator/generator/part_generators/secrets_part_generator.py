from pathlib import Path

from typing import Any

from .part_generator_base import PartGeneratorBase


class SecretsPartGenerator(PartGeneratorBase):
    """Write ``.secrets.toml``, or the ``.secrets.toml.example`` it is copied from.

    Two files with the same content and different fates: ``.secrets.toml`` is what the project
    runs against and is git-ignored, and ``.secrets.toml.example`` is what is committed so that
    the next person cloning the repository knows which keys to fill in. A scaffold that writes
    only the ignored one leaves nothing behind in the repository at all.

    **The leading dot is load-bearing.** ``DEFAULT_SETTINGS_FILES`` -- what ``entrypoint.py``
    hands to ``Config``, and the image's contract with the project -- is
    ``["settings.toml", ".secrets.toml"]``. Written without the dot the file was never loaded by
    anything, so a scaffolded project with the vLLM provider it is given failed
    ``Config.validate()`` with ``Missing API key for vLLM provider`` before it could serve a
    request. It is also Dynaconf's own convention, and the same shape as ``.env``.
    """

    def __init__(self, config: dict[str, Any], template_dir: str | Path, src_path: str, *, example: bool = False) -> None:
        super().__init__(config, template_dir, src_path)
        self.template_file_name = None
        self._example = example
        self.template_vars["content"] = self._create_secrets_content()

    def to_py_file_name(self) -> str:
        return ".secrets.toml.example" if self._example else ".secrets.toml"

    def _create_secrets_content(self) -> str:
        return '[default]\nmodel_api_key = "Your-API-Key"\n'
