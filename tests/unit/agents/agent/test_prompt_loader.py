"""Unit tests for the PromptLoader utility."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from blueprint.agents.agent.prompt_loader import PromptLoader
from blueprint.agents.config import Config


class TestPromptLoader:
    """Test suite for PromptLoader search and path handling."""

    @staticmethod
    def _config_with_values(
        *,
        prompt_search_paths: list[str] | None = None,
        package_root: Path | None = None,
    ) -> Config:
        """Create a config mock returning the supplied path values."""

        config = Mock(spec=Config)

        def get_side_effect(key: str, default=None):
            if key == "prompt_search_paths":
                return prompt_search_paths if prompt_search_paths is not None else default
            return default

        config.get.side_effect = get_side_effect
        config.get_package_root.return_value = package_root
        return config

    def test_load_prompt_from_config_search_paths(self, tmp_path: Path) -> None:
        """PromptLoader should load using search paths supplied via config.get."""

        prompt_dir = tmp_path / "custom"
        prompt_dir.mkdir()
        (prompt_dir / "system.prompt").write_text("Hello world\n")

        config = self._config_with_values(prompt_search_paths=[str(prompt_dir)])

        result = PromptLoader.load_prompt("system", config)

        assert result == "Hello world"

    def test_load_prompt_uses_absolute_path_argument(self, tmp_path: Path) -> None:
        """An explicit absolute path argument should be honored when valid."""

        explicit_dir = tmp_path / "explicit"
        explicit_dir.mkdir()
        (explicit_dir / "greeting.prompt").write_text("Hi there")

        config = self._config_with_values(prompt_search_paths=[])

        result = PromptLoader.load_prompt("greeting", config, path=str(explicit_dir))

        assert result == "Hi there"

    def test_load_prompt_uses_package_root_prompts_directory(self, tmp_path: Path) -> None:
        """Package root /prompts directory referenced via config should be searched."""

        package_root = tmp_path / "package_root"
        prompts_dir = package_root / "prompts"
        prompts_dir.mkdir(parents=True)
        (prompts_dir / "instruction.prompt").write_text("package prompt")

        config = self._config_with_values(package_root=package_root)

        result = PromptLoader.load_prompt("instruction", config)

        assert result == "package prompt"

    def test_load_prompt_logs_warning_for_relative_path(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """Relative explicit paths should warn and fall back to configured search paths."""

        fallback_dir = tmp_path / "fallback"
        fallback_dir.mkdir()
        (fallback_dir / "tool.prompt").write_text("chain result")

        config = self._config_with_values(prompt_search_paths=[str(fallback_dir)])

        with caplog.at_level("WARNING"):
            result = PromptLoader.load_prompt("tool", config, path="relative/path")

        assert "not absolute" in caplog.text
        assert result == "chain result"

    def test_load_prompt_raises_file_not_found_when_missing(self) -> None:
        """A helpful FileNotFoundError should be raised when prompt is missing."""

        config = self._config_with_values(prompt_search_paths=[])

        with pytest.raises(FileNotFoundError) as exc:
            PromptLoader.load_prompt("missing", config)

        assert "missing.prompt" in str(exc.value)

    def test_ensure_path_converts_relative_to_absolute(self) -> None:
        """_ensure_path should resolve relative strings into absolute paths."""

        relative_path = "some/relative/path"

        resolved = PromptLoader._ensure_path(relative_path)

        assert resolved == Path.cwd() / relative_path