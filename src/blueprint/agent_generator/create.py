"""
Create command for generating agent microservice from configuration.

Usage:
    python -m blueprint.agent_generator.create [config_file]

If config_file is not provided, looks for a *_config.json file in the current directory.
"""

import glob
import os
import sys

from .generator.generator import main as generate_microservice


def find_config_file() -> str:
    """Find a config file in the current directory."""
    config_files = list(glob.glob("*_config.json"))

    if not config_files:
        print("Error: No configuration file found in the current directory.", file=sys.stderr)
        print("Please run 'python -m blueprint.agent_generator.setup' first or specify a config file.", file=sys.stderr)
        sys.exit(1)

    if len(config_files) > 1:
        print("Multiple config files found. Please specify which one to use:", file=sys.stderr)
        for i, file in enumerate(config_files, 1):
            print(f"  {i}. {file}", file=sys.stderr)

        try:
            choice = int(input("Enter the number of the config file to use: "))
            if 1 <= choice <= len(config_files):
                return config_files[choice - 1]
            raise ValueError("Invalid selection")
        except (ValueError, IndexError):
            print("Error: Invalid selection.", file=sys.stderr)
            sys.exit(1)

    return config_files[0]


def main():
    # Get config file path
    if len(sys.argv) > 1:
        config_path = sys.argv[1]
        if not os.path.isfile(config_path):
            print(f"Error: Config file not found: {config_path}", file=sys.stderr)
            sys.exit(1)
    else:
        config_path = find_config_file()

    # Use the current directory as output directory
    output_dir = os.getcwd()

    print(f"Generating microservice from: {os.path.basename(config_path)}")
    print(f"Output directory: {output_dir}")

    try:
        # Make sure we're using absolute paths
        config_path = os.path.abspath(config_path)
        output_dir = os.path.abspath(output_dir)

        generate_microservice(config_path, output_dir)

        print("\nMicroservice generated successfully!")
        print("Next steps:")
        print(f"1. Review the generated files in: {output_dir}")
        print(
            '2. If the agent microservice uses LLM agents, add the "model_api_key" to environment variables '
            'using "DYNACONF_MODEL_API_KEY" or simply add a "model_api_key" to the settings.toml without an '
            "actual key for testing (otherwise the agent microservice will not start)."
        )
        print('3. Run the microservice: "uvicorn src.main:app"')
        print("4. After confirming, that the service runs, add actual business logic to the microservice.")

    except Exception as e:
        print(f"\nError generating microservice: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
