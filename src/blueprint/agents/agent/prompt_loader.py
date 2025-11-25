"""Utility for loading system prompts from files."""

import logging
from pathlib import Path

from blueprint.agents.config.config import Config


logger = logging.getLogger(__name__)


class PromptLoader:
    """Utility class for loading system prompts from the filesystem.

    Supports configurable prompt locations through settings.toml:
    - prompt_directory: Custom base directory for prompts
    - prompt_search_paths: Additional directories to search
    """

    @staticmethod
    def load_prompt(
        prompt_name: str,
        config: Config,
        path: str | None = None,
    ) -> str:
        """Load a system prompt file or from config.

        Searches for the prompt in this order:
        1. Prompt content defined in config (if provided) - HIGHEST PRIORITY
        2. Custom path from config (if provided)
        3. Additional search paths from config (if provided)
        4. Package root prompts directory (if package_root is provided)
        5. Project src/prompts directory
        6. Primary: `<module_dir>/../prompts/<prompt_name>.prompt`
        7. Fallback: `<module_dir>/prompts/<prompt_name>.prompt`
        8. Fallback: `<module_dir>/<prompt_name>.prompt`

        Args:
            prompt_name: Name of the prompt file (without .prompt extension).
            agent_class: The agent class requesting the prompt.
            config: Optional prompt configuration (dict or PromptConfig model) with keys:
                   - prompts: Dict of prompt names to prompt content (highest priority)
                   - custom_path: Custom prompt directory path
                   - search_paths: List of additional search paths
            package_root: Optional root path for the package (e.g., where main.py resides).
                         Used to locate prompts in package_root/prompts directory.

        Returns:
            Prompt text content.

        Raises:
            FileNotFoundError: If prompt file doesn't exist in any location.
        """
        search_roots: list[Path | str] = []
        searched_locations: list[Path] = []

        # 1. Config overrides have highest priority
        search_paths: list[str] = []
        if config:
            search_paths = config.get("prompt_search_paths", []) or []
            logger.debug("Added search paths from config: %s", search_paths)
            search_roots.extend(search_paths)

        # 2. check if path is given
        if path:
            if not Path(path).is_absolute():
                logger.warning("Prompt path '%s' is not absolute, falling back to search paths", path)
            elif not Path(path).exists():
                logger.warning("Prompt path '%s' does not exist, falling back to search paths", path)
            else:
                logger.debug("Using path parameter search root '%s'", path)
                search_roots.append(path)

        # 3. check in package prompts directory
        package_root = config.get_package_root() if config else None
        if package_root:
            package_root_path = PromptLoader._ensure_path(package_root)
            search_roots.append(package_root_path / "prompts")
            logger.debug("Added package root prompts directory: %s", package_root_path / "prompts")

        for prompt_directory in search_roots:
            # skip directory if does not exist or is not absolute
            prompt_directory = PromptLoader._ensure_path(prompt_directory)
            if not prompt_directory.is_absolute():
                continue
            if not prompt_directory.exists():
                searched_locations.append(prompt_directory / f"{prompt_name}.prompt")
                continue

            # check if file exists in current directory with {prompt_name}.prompt
            prompt_path = prompt_directory / f"{prompt_name}.prompt"
            searched_locations.append(prompt_path)
            if prompt_path.exists():
                with open(prompt_path) as f:
                    return f.read().strip()

        # If not found in any location, raise error with all attempted paths
        if not searched_locations and search_paths:
            searched_locations = [PromptLoader._ensure_path(path) / f"{prompt_name}.prompt" for path in search_paths]

        if searched_locations:
            locations_msg = "\n  - " + "\n  - ".join(str(p) for p in searched_locations)
        else:
            locations_msg = " (no valid search locations configured)"

        raise FileNotFoundError(f"Prompt file '{prompt_name}.prompt' not found.{locations_msg}")

    @staticmethod
    def _ensure_path(path_value: str | Path) -> Path:
        """Convert a string or Path into an absolute Path."""

        path_obj = Path(path_value).expanduser()
        if path_obj.is_absolute():
            return path_obj
        return Path.cwd() / path_obj
