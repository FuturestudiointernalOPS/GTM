"""Read settings from the .env file, safely."""

import os

try:
    from dotenv import load_dotenv
except ImportError as error:  # pragma: no cover - depends on the interpreter
    raise RuntimeError(
        "python-dotenv is missing: run the project with .venv/bin/python "
        "(or activate .venv first) and install requirements-dev.txt"
    ) from error

load_dotenv()


def require(name: str) -> str:
    """Return a setting that must exist, or stop with a clear message."""
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing setting: {name} (add it to the .env file)")
    return value


def optional(name: str, default=None):
    """Return a setting that may be missing, with a default value."""
    return os.getenv(name, default)
