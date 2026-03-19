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