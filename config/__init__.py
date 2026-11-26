"""Project configuration. Importing it also keeps secrets out of the logs."""

from config import log_safety

log_safety.install()
