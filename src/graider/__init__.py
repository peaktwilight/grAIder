"""graider package."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("graider")
except PackageNotFoundError:  # not installed (e.g. running from a raw checkout)
    __version__ = "0.0.0"

__all__ = ["__version__"]
