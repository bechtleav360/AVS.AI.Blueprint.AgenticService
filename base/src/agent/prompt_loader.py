"""Utility for loading system prompts from files."""

import inspect
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

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
        agent_class: type,
        config: Optional[Dict[str, Any]] = None
    ) -> str:
        """Load a system prompt file based on the agent class location.
        
        Searches for the prompt file in multiple locations:
        1. Custom path from config (if provided)
        2. Additional search paths from config (if provided)
        3. Primary: `<module_dir>/../prompts/<prompt_name>.prompt`
        4. Fallback: `<module_dir>/prompts/<prompt_name>.prompt`
        5. Fallback: `<module_dir>/<prompt_name>.prompt`
        
        Args:
            prompt_name: Name of the prompt file (without .prompt extension).
            agent_class: The agent class requesting the prompt.
            config: Optional prompt configuration dict with keys:
                   - custom_path: Custom prompt directory path
                   - search_paths: List of additional search paths
            
        Returns:
            Prompt text content.
            
        Raises:
            FileNotFoundError: If prompt file doesn't exist in any location.
        """
        search_paths = PromptLoader._get_prompt_search_paths(
            prompt_name, agent_class, config
        )
        
        for prompt_path in search_paths:
            if prompt_path.exists():
                logger.debug("Loading prompt from: %s", prompt_path)
                return prompt_path.read_text().strip()
        
        # If not found in any location, raise error with all attempted paths
        searched_locations = "\n  - ".join(str(p) for p in search_paths)
        raise FileNotFoundError(
            f"Prompt file '{prompt_name}.prompt' not found for {agent_class.__name__}. "
            f"Searched locations:\n  - {searched_locations}"
        )

    @staticmethod
    def _get_prompt_search_paths(
        prompt_name: str,
        agent_class: type,
        config: Optional[Dict[str, Any]] = None
    ) -> List[Path]:
        """Get list of paths to search for the prompt file.
        
        Args:
            prompt_name: Name of the prompt file (without .prompt extension).
            agent_class: The agent class requesting the prompt.
            config: Optional prompt configuration dict.
            
        Returns:
            List of Path objects to search in order of priority.
        """
        subclass_file = Path(inspect.getfile(agent_class)).resolve()
        module_dir = subclass_file.parent
        filename = f"{prompt_name}.prompt"
        
        search_paths: List[Path] = []
        
        # 1. Add custom path from config if provided
        if config and config.get("custom_path"):
            custom_path = Path(config["custom_path"])
            if not custom_path.is_absolute():
                # Resolve relative paths from module directory
                custom_path = module_dir / custom_path
            search_paths.append(custom_path / filename)
            logger.debug("Added custom prompt path from config: %s", custom_path)
        
        # 2. Add additional search paths from config
        if config and config.get("search_paths"):
            for search_path_str in config["search_paths"]:
                search_path = Path(search_path_str)
                if not search_path.is_absolute():
                    search_path = module_dir / search_path
                search_paths.append(search_path / filename)
            logger.debug(
                "Added %d additional search paths from config",
                len(config["search_paths"])
            )
        
        # 3. Add default search paths based on agent class location
        default_paths = [
            module_dir.parent / "prompts" / filename,  # ../prompts/
            module_dir / "prompts" / filename,          # ./prompts/
            module_dir / filename,                      # ./
        ]
        search_paths.extend(default_paths)
        
        logger.debug(
            "Prompt search paths for %s: %s",
            agent_class.__name__,
            [str(p) for p in search_paths]
        )
        
        return search_paths

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
        
        logger.debug(
            "Resolved prompt directory for %s: %s",
            agent_class.__name__,
            prompt_dir
        )
        
        return prompt_dir
