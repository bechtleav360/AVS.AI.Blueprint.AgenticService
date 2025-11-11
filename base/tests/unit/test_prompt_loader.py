"""Unit tests for PromptLoader."""

from pathlib import Path
from unittest.mock import Mock, mock_open, patch

import pytest

from base.src.agent.prompt_loader import PromptLoader


class TestPromptLoader:
    """Test suite for PromptLoader."""

    @pytest.fixture
    def mock_agent_class(self):
        """Create a mock agent class."""
        mock_class = Mock()
        mock_class.__name__ = "TestAgent"
        return mock_class

    def test_load_prompt_from_file(self, mock_agent_class, tmp_path):
        """Test loading prompt from file."""
        # Create test prompt file
        prompt_dir = tmp_path / "prompts"
        prompt_dir.mkdir()
        prompt_file = prompt_dir / "test.prompt"
        prompt_file.write_text("Test system prompt")

        with patch("inspect.getfile") as mock_getfile:
            mock_getfile.return_value = str(tmp_path / "agent.py")

            result = PromptLoader.load_prompt("test", mock_agent_class)

            assert result == "Test system prompt"

    def test_load_prompt_strips_whitespace(self, mock_agent_class, tmp_path):
        """Test loaded prompt has whitespace stripped."""
        prompt_dir = tmp_path / "prompts"
        prompt_dir.mkdir()
        prompt_file = prompt_dir / "test.prompt"
        prompt_file.write_text("  Test prompt with spaces  \n")

        with patch("inspect.getfile") as mock_getfile:
            mock_getfile.return_value = str(tmp_path / "agent.py")

            result = PromptLoader.load_prompt("test", mock_agent_class)

            assert result == "Test prompt with spaces"

    def test_load_prompt_file_not_found_raises_error(self, mock_agent_class, tmp_path):
        """Test loading non-existent prompt raises FileNotFoundError."""
        with patch("inspect.getfile") as mock_getfile:
            mock_getfile.return_value = str(tmp_path / "agent.py")

            with pytest.raises(FileNotFoundError, match="not found"):
                PromptLoader.load_prompt("nonexistent", mock_agent_class)

    def test_load_prompt_searches_multiple_paths(self, mock_agent_class, tmp_path):
        """Test prompt loader searches multiple paths."""
        # Create prompt in fallback location
        prompt_file = tmp_path / "test.prompt"
        prompt_file.write_text("Found in fallback")

        with patch("inspect.getfile") as mock_getfile:
            mock_getfile.return_value = str(tmp_path / "agent.py")

            result = PromptLoader.load_prompt("test", mock_agent_class)

            assert result == "Found in fallback"

    def test_load_prompt_with_custom_path(self, mock_agent_class, tmp_path):
        """Test loading prompt from custom path in config."""
        custom_dir = tmp_path / "custom_prompts"
        custom_dir.mkdir()
        prompt_file = custom_dir / "test.prompt"
        prompt_file.write_text("Custom prompt")

        config = {"custom_path": str(custom_dir)}

        with patch("inspect.getfile") as mock_getfile:
            mock_getfile.return_value = str(tmp_path / "agent.py")

            result = PromptLoader.load_prompt("test", mock_agent_class, config)

            assert result == "Custom prompt"

    def test_load_instruction_prompt_formats_template(self, mock_agent_class, tmp_path):
        """Test load_instruction_prompt formats template with variables."""
        prompt_dir = tmp_path / "prompts"
        prompt_dir.mkdir()
        prompt_file = prompt_dir / "instruction.prompt"
        prompt_file.write_text("Process this: {data}\nWith context: {context}")

        with patch("inspect.getfile") as mock_getfile:
            mock_getfile.return_value = str(tmp_path / "agent.py")

            result = PromptLoader.load_instruction_prompt(
                "instruction",
                mock_agent_class,
                config=None,
                data="test_data",
                context="test_context",
            )

            assert result == "Process this: test_data\nWith context: test_context"

    def test_load_instruction_prompt_missing_variable_raises_error(self, mock_agent_class, tmp_path):
        """Test load_instruction_prompt raises error for missing variable."""
        prompt_dir = tmp_path / "prompts"
        prompt_dir.mkdir()
        prompt_file = prompt_dir / "instruction.prompt"
        prompt_file.write_text("Process this: {data}\nWith context: {missing}")

        with patch("inspect.getfile") as mock_getfile:
            mock_getfile.return_value = str(tmp_path / "agent.py")

            with pytest.raises(KeyError, match="Missing template variable"):
                PromptLoader.load_instruction_prompt(
                    "instruction",
                    mock_agent_class,
                    config=None,
                    data="test_data",
                )

    def test_load_instruction_prompt_with_no_variables(self, mock_agent_class, tmp_path):
        """Test load_instruction_prompt works with no template variables."""
        prompt_dir = tmp_path / "prompts"
        prompt_dir.mkdir()
        prompt_file = prompt_dir / "instruction.prompt"
        prompt_file.write_text("Static instruction with no variables")

        with patch("inspect.getfile") as mock_getfile:
            mock_getfile.return_value = str(tmp_path / "agent.py")

            result = PromptLoader.load_instruction_prompt("instruction", mock_agent_class, config=None)

            assert result == "Static instruction with no variables"

    def test_load_instruction_prompt_with_multiple_variables(self, mock_agent_class, tmp_path):
        """Test load_instruction_prompt with multiple template variables."""
        prompt_dir = tmp_path / "prompts"
        prompt_dir.mkdir()
        prompt_file = prompt_dir / "instruction.prompt"
        prompt_file.write_text("User: {user}\nAction: {action}\nData: {data}\nPriority: {priority}")

        with patch("inspect.getfile") as mock_getfile:
            mock_getfile.return_value = str(tmp_path / "agent.py")

            result = PromptLoader.load_instruction_prompt(
                "instruction",
                mock_agent_class,
                config=None,
                user="john",
                action="process",
                data="invoice",
                priority="high",
            )

            expected = "User: john\nAction: process\nData: invoice\nPriority: high"
            assert result == expected

    def test_load_instruction_prompt_with_dict_variable(self, mock_agent_class, tmp_path):
        """Test load_instruction_prompt can format dict variables."""
        prompt_dir = tmp_path / "prompts"
        prompt_dir.mkdir()
        prompt_file = prompt_dir / "instruction.prompt"
        prompt_file.write_text("Metadata: {metadata}")

        with patch("inspect.getfile") as mock_getfile:
            mock_getfile.return_value = str(tmp_path / "agent.py")

            result = PromptLoader.load_instruction_prompt(
                "instruction",
                mock_agent_class,
                config=None,
                metadata={"key": "value", "count": 42},
            )

            assert "key" in result
            assert "value" in result

    def test_get_prompt_dir_returns_correct_path(self, mock_agent_class, tmp_path):
        """Test get_prompt_dir returns correct prompts directory."""
        agent_file = tmp_path / "agent" / "runtime.py"
        agent_file.parent.mkdir(parents=True)

        with patch("inspect.getfile") as mock_getfile:
            mock_getfile.return_value = str(agent_file)

            result = PromptLoader.get_prompt_dir(mock_agent_class)

            expected = tmp_path / "prompts"
            assert result == expected

    def test_load_prompt_with_search_paths(self, mock_agent_class, tmp_path):
        """Test loading prompt from additional search paths."""
        search_dir = tmp_path / "search_path"
        search_dir.mkdir()
        prompt_file = search_dir / "test.prompt"
        prompt_file.write_text("Found in search path")

        config = {"search_paths": [str(search_dir)]}

        with patch("inspect.getfile") as mock_getfile:
            mock_getfile.return_value = str(tmp_path / "agent.py")

            result = PromptLoader.load_prompt("test", mock_agent_class, config)

            assert result == "Found in search path"

    def test_load_instruction_prompt_uses_custom_config(self, mock_agent_class, tmp_path):
        """Test load_instruction_prompt respects custom config."""
        custom_dir = tmp_path / "custom"
        custom_dir.mkdir()
        prompt_file = custom_dir / "instruction.prompt"
        prompt_file.write_text("Custom: {value}")

        config = {"custom_path": str(custom_dir)}

        with patch("inspect.getfile") as mock_getfile:
            mock_getfile.return_value = str(tmp_path / "agent.py")

            result = PromptLoader.load_instruction_prompt("instruction", mock_agent_class, config=config, value="test")

            assert result == "Custom: test"

    def test_load_instruction_prompt_error_shows_available_vars(self, mock_agent_class, tmp_path):
        """Test error message shows available template variables."""
        prompt_dir = tmp_path / "prompts"
        prompt_dir.mkdir()
        prompt_file = prompt_dir / "instruction.prompt"
        prompt_file.write_text("Need: {missing}")

        with patch("inspect.getfile") as mock_getfile:
            mock_getfile.return_value = str(tmp_path / "agent.py")

            with pytest.raises(KeyError, match="Available variables"):
                PromptLoader.load_instruction_prompt(
                    "instruction",
                    mock_agent_class,
                    config=None,
                    var1="value1",
                    var2="value2",
                )
