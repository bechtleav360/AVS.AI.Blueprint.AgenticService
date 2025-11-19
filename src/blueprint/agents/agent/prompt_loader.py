"""Utility for loading system prompts from files."""

import inspect
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Union

if TYPE_CHECKING:
    from ..models.config import PromptConfig

logger = logging.getLogger(__name__)


class PromptLoader:
    """Utility class for loading system prompts from the filesystem.

    Supports configurable prompt locations through settings.toml:
    - prompt_directory: Custom base directory for prompts
    - prompt_search_paths: Additional directories to search
    """

    @staticmethod
    def load_prompt(prompt_name: str, agent_class: type, config: Union[dict[str, Any], "PromptConfig", None] = None) -> str:
        """Load a system prompt file or from config.

        Searches for the prompt in this order:
        1. Prompt content defined in config (if provided) - HIGHEST PRIORITY
        2. Custom path from config (if provided)
        3. Additional search paths from config (if provided)
        4. Project src/prompts directory
        5. Primary: `<module_dir>/../prompts/<prompt_name>.prompt`
        6. Fallback: `<module_dir>/prompts/<prompt_name>.prompt`
        7. Fallback: `<module_dir>/<prompt_name>.prompt`

        Args:
            prompt_name: Name of the prompt file (without .prompt extension).
            agent_class: The agent class requesting the prompt.
            config: Optional prompt configuration (dict or PromptConfig model) with keys:
                   - prompts: Dict of prompt names to prompt content (highest priority)
                   - custom_path: Custom prompt directory path
                   - search_paths: List of additional search paths

        Returns:
            Prompt text content.

        Raises:
            FileNotFoundError: If prompt file doesn't exist in any location.
        """
        # 1. Check if prompt is defined directly in config (highest priority)
        if config:
            # Handle both dict and Pydantic model
            prompts_dict = None
            if isinstance(config, dict):
                prompts_dict = config.get("prompts")
            else:
                prompts_dict = getattr(config, "prompts", None)

            if prompts_dict and prompt_name in prompts_dict:
                prompt_content = prompts_dict[prompt_name]
                logger.debug("Loading prompt from config: %s", prompt_name)
                return prompt_content.strip() if isinstance(prompt_content, str) else prompt_content

        # 2. Search filesystem for prompt file
        search_paths = PromptLoader._get_prompt_search_paths(prompt_name, agent_class, config)

        for prompt_path in search_paths:
            if prompt_path.exists():
                logger.debug("Loading prompt from: %s", prompt_path)
                return prompt_path.read_text().strip()

        # If not found in any location, raise error with all attempted paths
        searched_locations = "\n  - ".join(str(p) for p in search_paths)
        raise FileNotFoundError(
            f"Prompt file '{prompt_name}.prompt' not found for {agent_class.__name__}. " f"Searched locations:\n  - {searched_locations}"
        )

    @staticmethod
    def _get_prompt_search_paths(
        prompt_name: str, agent_class: type, config: Union[dict[str, Any], "PromptConfig", None] = None
    ) -> list[Path]:
        """Get list of paths to search for the prompt file.

        Args:
            prompt_name: Name of the prompt file (without .prompt extension).
            agent_class: The agent class requesting the prompt.
            config: Optional prompt configuration (dict or PromptConfig model).

        Returns:
            List of Path objects to search in order of priority.
        """
        subclass_file = Path(inspect.getfile(agent_class)).resolve()
        module_dir = subclass_file.parent
        filename = f"{prompt_name}.prompt"

        search_paths: list[Path] = []

        # 1. Add custom path from config if provided
        if config:
            # Handle both dict and Pydantic model
            custom_path_value = None
            if isinstance(config, dict):
                custom_path_value = config.get("custom_path")
            else:
                custom_path_value = config.custom_path

            if custom_path_value:
                custom_path = Path(custom_path_value)
                if not custom_path.is_absolute():
                    # Resolve relative paths from current working directory
                    custom_path = Path.cwd() / custom_path
                search_paths.append(custom_path / filename)
                logger.debug("Added custom prompt path from config: %s", custom_path)

        # 2. Add additional search paths from config
        if config:
            # Handle both dict and Pydantic model
            search_paths_config = None
            if isinstance(config, dict):
                search_paths_config = config.get("search_paths")
            else:
                search_paths_config = config.search_paths

            if search_paths_config:
                # Handle both list and string (for backward compatibility)
                if isinstance(search_paths_config, str):
                    # Single path as string
                    search_path = Path(search_paths_config)
                    if not search_path.is_absolute():
                        search_path = Path.cwd() / search_path
                    search_paths.append(search_path / filename)
                    logger.debug("Added search path from config: %s", search_path)
                elif isinstance(search_paths_config, (list, tuple)):
                    # Multiple paths as list
                    for search_path_str in search_paths_config:
                        search_path = Path(search_path_str)
                        if not search_path.is_absolute():
                            search_path = Path.cwd() / search_path
                        search_paths.append(search_path / filename)
                    logger.debug(
                        "Added %d additional search paths from config",
                        len(search_paths_config),
                    )
                else:
                    logger.warning("Invalid search_paths config type: %s", type(search_paths_config))

        # 3. Add project src/prompts directory (for examples and projects)
        # Search up the directory tree for a src/prompts directory
        current = Path.cwd()
        for _ in range(10):  # Limit search depth to avoid infinite loops
            project_prompts = current / "src" / "prompts"
            if project_prompts.exists():
                search_paths.append(project_prompts / filename)
                logger.debug("Added project prompts directory: %s", project_prompts)
                break
            parent = current.parent
            if parent == current:  # Reached filesystem root
                break
            current = parent

        # 4. Add default search paths based on agent class location
        default_paths = [
            module_dir.parent / "prompts" / filename,  # ../prompts/
            module_dir / "prompts" / filename,  # ./prompts/
            module_dir / filename,  # ./
        ]
        search_paths.extend(default_paths)

        logger.debug(
            "Prompt search paths for %s: %s",
            agent_class.__name__,
            [str(p) for p in search_paths],
        )

        return search_paths

    @staticmethod
    def load_instruction_prompt(
        prompt_name: str,
        caller_class: type,
        config: Union[dict[str, Any], "PromptConfig", None] = None,
        **template_vars: Any,
    ) -> str:
        """Load an instruction prompt file and format it with template variables.

        This method loads a prompt file and formats it using Python's str.format()
        with the provided template variables. This allows handlers to load
        instruction prompts that can be customized at runtime via configuration.

        Args:
            prompt_name: Name of the prompt file (without .prompt extension).
            caller_class: The class requesting the prompt (for path resolution).
            config: Optional prompt configuration (dict or PromptConfig model) with keys:
                   - custom_path: Custom prompt directory path
                   - search_paths: List of additional search paths
            **template_vars: Variables to use in template formatting.

        Returns:
            Formatted prompt text.

        Raises:
            FileNotFoundError: If prompt file doesn't exist.
            KeyError: If template variable is missing.

        Example:
            instruction = PromptLoader.load_instruction_prompt(
                "invoice_instruction",
                self.__class__,
                config=prompt_config,
                invoice_text=text,
                metadata=meta
            )
        """
        # Load the prompt template
        template = PromptLoader.load_prompt(prompt_name, caller_class, config)

        # Format with template variables
        try:
            formatted = template.format(**template_vars)
            logger.debug(
                "Formatted instruction prompt '%s' with %d variables",
                prompt_name,
                len(template_vars),
            )
            return formatted
        except KeyError as e:
            raise KeyError(
                f"Missing template variable in prompt '{prompt_name}': {e}. " f"Available variables: {list(template_vars.keys())}"
            ) from e

    @staticmethod
    def get_prompt_dir(agent_class: type) -> Path:
        """Determine the directory containing prompt files for an agent class.

        Default behaviour:
        - For a subclass defined in `.../custom/agent/<file>.py`, this returns
          `.../custom/prompts` by walking up one directory from the subclass
          module directory and appending `prompts`.

        Args:
            agent_class: The agent class to find prompts for.

        Returns:
            Path to the prompts directory.
        """
        subclass_file = Path(inspect.getfile(agent_class)).resolve()
        module_dir = subclass_file.parent  # e.g., .../custom/agent
        prompt_dir = module_dir.parent / "prompts"  # e.g., .../custom/prompts

        logger.debug("Resolved prompt directory for %s: %s", agent_class.__name__, prompt_dir)

        return prompt_dir
