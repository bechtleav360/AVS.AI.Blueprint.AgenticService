import re


def camel_to_snake(name: str) -> str:
    """
    Convert a CamelCase class name to snake_case variable name.
    Handles acronyms better by treating sequences of 2+ uppercase letters as a single word.
    """

    # Handle the case of multiple uppercase letters (acronyms) followed by lowercase
    s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    # Handle the case of a lowercase letter or number followed by an uppercase letter
    s2 = re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1)
    # Handle the case of multiple uppercase letters at the end of the string
    s3 = re.sub("([A-Z])([A-Z][a-z])", r"\1_\2", s2)
    return s3.lower()


def parse_bool(value: object, key: str) -> bool:
    """Coerce a config value to a bool, accepting the strings an environment variable delivers.

    Dynaconf returns a real bool for ``key = true`` in a TOML file, but an environment
    override arrives as text, so ``"true"`` has to mean the same thing as ``True``.
    Anything else raises rather than being treated as falsy: a typo that silently disables
    a feature is the failure this exists to prevent.

    Args:
        value: The raw config value.
        key: The config key, used only in the error message.

    Returns:
        The parsed boolean.

    Raises:
        ValueError: If the value is neither a bool nor a recognised boolean string.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("true", "1", "yes"):
            return True
        if normalized in ("false", "0", "no"):
            return False
    raise ValueError(f"Config key '{key}' must be a boolean, got {value!r}.")
