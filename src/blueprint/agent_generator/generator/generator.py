"""Agent microservice generator."""

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from .part_generators import (
    APIPartGenerator,
    CopyPartGenerator,
    DomainModelPartGenerator,
    DTOPartGenerator,
    HandlerPartGenerator,
    InitPartGenerator,
    MainPartGenerator,
    MapperPartGenerator,
    ServicePartGenerator,
    SettingsPartGenerator,
    SecretsPartGenerator
)

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


class AgentGenerator:
    """Generator for creating agent microservices."""

    def __init__(self, config_path: str, output_dir: str):
        """Initialize the generator with config and output directory.

        Args:
            config_path: Path to the JSON configuration file
            output_dir: Directory where the new microservice will be created

        Raises:
            FileNotFoundError: If template directory is not found
        """
        logger.info(f"Initializing AgentGenerator with config: {config_path}, output_dir: {output_dir}")
        self.config_path = Path(config_path).absolute()
        self.output_dir = Path(output_dir).absolute()
        self.template_dir = (Path(__file__).parent.parent / "base_files").absolute()
        self.config: dict[str, Any] = {}

        logger.info(f"Using template directory: {self.template_dir}")
        logger.info(f"Output will be written to: {self.output_dir}")

        # Verify template directory exists
        if not self.template_dir.exists():
            error_msg = f"Template directory not found: {self.template_dir}"
            logger.error(error_msg)
            raise FileNotFoundError(error_msg)

        logger.debug("AgentGenerator initialization completed")

    def load_config(self) -> None:
        """Load and validate the configuration file.

        Raises:
            FileNotFoundError: If config file is not found
            ValueError: If config file contains invalid JSON or is missing required fields
            Exception: For any other errors during config loading
        """
        logger.info(f"Loading configuration from: {self.config_path}")

        if not self.config_path.exists():
            error_msg = f"Config file not found: {self.config_path}"
            logger.error(error_msg)
            raise FileNotFoundError(error_msg)

        try:
            with open(self.config_path) as f:
                logger.debug(f"Reading config file: {self.config_path}")
                self.config = json.load(f)
                logger.debug(f"Loaded config: {json.dumps(self.config, indent=2, default=str)}")

            if not self._config_is_valid():
                sys.exit(1)
            logger.info("Configuration is valid")

        except json.JSONDecodeError as e:
            error_msg = f"Invalid JSON in config file {self.config_path}: {e}"
            logger.error(error_msg, exc_info=True)
            raise ValueError(error_msg) from e
        except Exception as e:
            error_msg = f"Error loading config file {self.config_path}: {e}"
            logger.error(error_msg, exc_info=True)
            raise

    def _config_is_valid(self) -> bool:
        """Validate the configuration structure and cross-references.

        Returns:
            bool: True if configuration is valid, False otherwise
        """

        logger.info("Validating configuration...")
        has_errors = False

        # Check required top-level sections
        required_fields = ["name", "description", "communication_layer", "agent_layer", "service_layer", "domain_models"]
        missing_fields = [field for field in required_fields if field not in self.config]

        if missing_fields:
            logger.error(f"Missing required sections in config: {', '.join(missing_fields)}")
            has_errors = True

        # Get all service, agent, and model names for reference
        service_names = set(self.config.get("service_layer", {}).keys())
        agent_names = set(self.config.get("agent_layer", {}).keys())
        domain_model_names = set(self.config.get("domain_models", {}).keys())

        # Validate service layer
        for service_name, service in self.config.get("service_layer", {}).items():
            # Validate agent references
            for agent_name in service.get("uses_agents", []):
                if agent_name not in agent_names:
                    logger.error(
                        f"Service '{service_name}' references undefined agent '{agent_name}'. "
                        f"Available agents: {', '.join(agent_names) or 'none'}"
                    )
                    has_errors = True

            # Validate domain model references
            for model_name in service.get("uses_domain_models", []):
                if model_name not in domain_model_names:
                    logger.error(
                        f"Service '{service_name}' references undefined domain model '{model_name}'. "
                        f"Available models: {', '.join(domain_model_names) or 'none'}"
                    )
                    has_errors = True

            # Validate process function types
            if "process_function" in service:
                pf = service["process_function"]
                if pf.get("input_type") not in domain_model_names:
                    logger.error(
                        f"Service '{service_name}' process function has invalid input type '{pf.get('input_type')}'. "
                        f"Available models: {', '.join(domain_model_names) or 'none'}"
                    )
                    has_errors = True
                if pf.get("output_type") not in domain_model_names:
                    logger.error(
                        f"Service '{service_name}' process function has invalid output type '{pf.get('output_type')}'. "
                        f"Available models: {', '.join(domain_model_names) or 'none'}"
                    )
                    has_errors = True

        # Validate REST API configuration if present
        if self.config.get("communication_layer", {}).get("rest_api", {}).get("add_rest_api", False):
            rest_api = self.config["communication_layer"]["rest_api"]
            dto_classes = set(rest_api.get("dto_classes", {}).keys())

            # Validate DTO classes
            if not dto_classes:
                logger.error("REST API is enabled but no DTO classes are defined")
                has_errors = True

            # Validate service references
            for service_name in rest_api.get("uses_services", []):
                if service_name not in service_names:
                    logger.error(
                        f"REST API references undefined service '{service_name}'. "
                        f"Available services: {', '.join(service_names) or 'none'}"
                    )
                    has_errors = True

            # Validate endpoint functions
            for endpoint_name, endpoint in rest_api.get("endpoint_functions", {}).items():
                # Validate DTO references
                if endpoint.get("input_dto") not in dto_classes:
                    logger.error(
                        f"Endpoint '{endpoint_name}' references undefined input DTO '{endpoint.get('input_dto')}'. "
                        f"Available DTOs: {', '.join(dto_classes) or 'none'}"
                    )
                    has_errors = True
                if endpoint.get("output_dto") not in dto_classes:
                    logger.error(
                        f"Endpoint '{endpoint_name}' references undefined output DTO '{endpoint.get('output_dto')}'. "
                        f"Available DTOs: {', '.join(dto_classes) or 'none'}"
                    )
                    has_errors = True

                # Validate service reference
                service_name = endpoint.get("service")
                if service_name not in service_names:
                    logger.error(
                        f"Endpoint '{endpoint_name}' references undefined service '{service_name}'. "
                        f"Available services: {', '.join(service_names) or 'none'}"
                    )
                    has_errors = True

            # Validate mapper configuration
            if "mapper" in rest_api:
                mapper = rest_api["mapper"]
                for mapping in mapper.get("mappings", []):
                    # Validate source and target types
                    source = mapping.get("from", {})
                    target = mapping.get("to", {})

                    # Validate source
                    if source.get("type") == "dto" and source.get("name") not in dto_classes:
                        logger.error(
                            f"Mapper references undefined DTO '{source.get('name')}' as source. "
                            f"Available DTOs: {', '.join(dto_classes) or 'none'}"
                        )
                        has_errors = True
                    elif source.get("type") == "domain_model" and source.get("name") not in domain_model_names:
                        logger.error(
                            f"Mapper references undefined domain model '{source.get('name')}' as source. "
                            f"Available models: {', '.join(domain_model_names) or 'none'}"
                        )
                        has_errors = True

                    # Validate target
                    if target.get("type") == "dto" and target.get("name") not in dto_classes:
                        logger.error(
                            f"Mapper references undefined DTO '{target.get('name')}' as target. "
                            f"Available DTOs: {', '.join(dto_classes) or 'none'}"
                        )
                        has_errors = True
                    elif target.get("type") == "domain_model" and target.get("name") not in domain_model_names:
                        logger.error(
                            f"Mapper references undefined domain model '{target.get('name')}' as target. "
                            f"Available models: {', '.join(domain_model_names) or 'none'}"
                        )
                        has_errors = True

        # Validate handlers
        for handler_name, handler in self.config.get("communication_layer", {}).get("handlers", {}).items():
            for service_name in handler.get("uses_services", []):
                if service_name not in service_names:
                    logger.error(
                        f"Handler '{handler_name}' references undefined service '{service_name}'. "
                        f"Available services: {', '.join(service_names) or 'none'}"
                    )
                    has_errors = True

        # Validate communication layer for either REST API or handlers
        if not (
            self.config.get("communication_layer", {}).get("rest_api", {}).get("add_rest_api", False)
            or self.config.get("communication_layer", {}).get("handlers", {})
        ):
            logger.error("No communication layer configuration found. Please add either a REST API or handlers.")
            has_errors = True

        # Validate service layer - at least one service should be defined
        if not self.config.get("service_layer", {}):
            logger.error("No services defined in the service layer. Please add at least one service.")
            has_errors = True

        if has_errors:
            logger.error("Configuration validation failed. Please fix the above errors.")
            return False

        logger.info("Configuration is valid")
        return True

    def generate(self) -> None:
        """Generate the microservice based on the configuration.

        This is the main entry point for generating the microservice. It coordinates
        the entire generation process including copying template files and processing
        all templates with the provided configuration.

        Raises:
            RuntimeError: If there's an error during the generation process
        """
        logger.info("Starting microservice generation")
        logger.info(f"Project name: {self.config.get('name', 'Unnamed')}")
        logger.info(f"Output directory: {self.output_dir}")

        try:
            logger.info("Preparing output directory...")
            self._prepare_output_directory()

            logger.info("Copying template files...")
            self._create_files_from_templates()

            logger.info(f"Successfully created microservice in {self.output_dir}")
            print(f"Successfully created microservice in {self.output_dir}")

        except Exception as e:
            error_msg = f"Failed to generate microservice: {e}"
            logger.error(error_msg, exc_info=True)
            raise RuntimeError(error_msg) from e

    def _prepare_output_directory(self) -> None:
        """Create or clean the output directory."""
        if not self.output_dir.exists():
            self.output_dir.mkdir(parents=True, exist_ok=True)

    def _create_files_from_templates(self) -> None:
        """Create files from templates in the output directory.

        Raises:
            FileNotFoundError: If template directory or any whitelisted file is not found
            RuntimeError: If there's an error during file copying
        """
        logger.info(f"Copying whitelisted template files from {self.template_dir} to {self.output_dir}")

        if not self.template_dir.exists():
            error_msg = f"Template directory not found: {self.template_dir}"
            logger.error(error_msg)
            raise FileNotFoundError(error_msg)

        out = str(self.output_dir)
        try:
            # Create python files
            MainPartGenerator(self.config, self.template_dir, "src").create_file(out)
            DomainModelPartGenerator(self.config, self.template_dir, "src/models").create_file(out)
            # Only create API, DTO, and mapper files if REST API is enabled
            if self.config["communication_layer"]["rest_api"]["add_rest_api"]:
                APIPartGenerator(self.config, self.template_dir, "src/api").create_file(out)
                DTOPartGenerator(self.config, self.template_dir, "src/models").create_file(out)
                MapperPartGenerator(self.config, self.template_dir, "src/models").create_file(out)
            for service_name in self.config["service_layer"]:
                ServicePartGenerator(self.config, self.template_dir, "src/services", service_name).create_file(out)
            for handler_name in self.config["communication_layer"]["handlers"]:
                HandlerPartGenerator(self.config, self.template_dir, "src/handlers", handler_name).create_file(out)
            for agent_name in self.config["agent_layer"]:
                CopyPartGenerator(
                    self.config,
                    self.template_dir,
                    "src/prompts",
                    "prompt.prompt",
                    f"{self.config['agent_layer'][agent_name]['runtime_name']}.prompt",
                ).create_file(out)

            # Create Dockerfile
            CopyPartGenerator(self.config, self.template_dir, "", "Dockerfile", "Dockerfile").create_file(out)

            # Create .gitignore
            CopyPartGenerator(self.config, self.template_dir, "", "template_for_git_ignore.txt", ".gitignore").create_file(out)

            # Create settings.toml
            SettingsPartGenerator(self.config, self.template_dir, "").create_file(out)

            # Create secrets.toml with API key placeholder
            SecretsPartGenerator(self.config, self.template_dir, "").create_file()

            # Create __init__ files with imports
            InitPartGenerator(self.config, self.template_dir, "src", out).create_file(out)
            InitPartGenerator(self.config, self.template_dir, "src/api", out).create_file(out)
            InitPartGenerator(self.config, self.template_dir, "src/services", out).create_file(out)
            InitPartGenerator(self.config, self.template_dir, "src/models", out).create_file(out)
            InitPartGenerator(self.config, self.template_dir, "src/handlers", out).create_file(out)

            logger.info("Finished copying whitelisted template files")

        except Exception as e:
            error_msg = f"Error copying template files: {e}"
            logger.error(error_msg, exc_info=True)
            raise RuntimeError(error_msg) from e


def main(config_path: str, output_dir: str) -> None:
    """Run the generator with the given configuration and output directory.

    Args:
        config_path: Path to the JSON configuration file
        output_dir: Directory where the microservice will be created
    """
    try:
        generator = AgentGenerator(config_path, output_dir)
        generator.load_config()
        generator.generate()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cli() -> None:
    """Command line interface for the generator."""
    import argparse

    parser = argparse.ArgumentParser(description="Generate an agent microservice from a template.")
    parser.add_argument("config", help="Path to the JSON configuration file")
    parser.add_argument(
        "output_dir", nargs="?", default=os.getcwd(), help="Directory where the microservice will be created (default: current directory)"
    )

    args = parser.parse_args()
    main(args.config, args.output_dir)


if __name__ == "__main__":
    cli()
