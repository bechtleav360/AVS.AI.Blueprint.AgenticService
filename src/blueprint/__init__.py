"""Blueprint agents framework."""

from importlib import metadata

try:
    __version__ = metadata.version("avs-blueprint-agents")
except metadata.PackageNotFoundError:
    __version__ = "0.3.0"
