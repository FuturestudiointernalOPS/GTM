"""Keep secrets out of the logs, whatever level an entry point chooses.

Why: the HTTP clients (httpx, and httpx2 used by the OpenAI SDK) log every
request URL at INFO. Telegram puts the bot token in the URL and SerpApi puts its
key in the query string, so an INFO log of a run used to contain both in clear.

Two layers, installed once when the ``config`` package is imported:

- the HTTP client loggers are capped at WARNING, so request lines never appear;
- a filter on those loggers and on the root handlers redacts any token or key
  that still reaches a message (an error text quoting a URL, for example).
"""

import logging
import re

HTTP_LOGGERS = ("httpx", "httpx2", "httpcore", "urllib3")

REDACTED = "***"

_PATTERNS = (
    # https://api.telegram.org/bot123456:ABC.../sendMessage
    (re.compile(r"(/bot)\d+:[A-Za-z0-9_-]+"), rf"\1{REDACTED}"),
    # ?api_key=... or &token=... in a query string
    (
        re.compile(r"((?:api_key|apikey|key|token|access_token)=)[^&\s\"']+", re.I),
        rf"\1{REDACTED}",
    ),
    # Authorization: Bearer ...
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+", re.I), rf"\1{REDACTED}"),
)


def redact(text: str) -> str:
    """Replace every known secret shape in ``text`` with ***."""
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class RedactSecrets(logging.Filter):
    """Rewrite the record's message so no secret is ever formatted out."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - a bad log call must not crash the run
            return True
        clean = redact(message)
        if clean != message:
            record.msg = clean
            record.args = None
        return True


_FILTER = RedactSecrets()


_installed = False


def install() -> None:
    """Cap the HTTP loggers and redact every record. Safe to call twice.

    The record factory covers every logger of the project without touching the
    entry points that call ``logging.basicConfig``.
    """
    global _installed
    for name in HTTP_LOGGERS:
        logger = logging.getLogger(name)
        logger.setLevel(logging.WARNING)
        if _FILTER not in logger.filters:
            logger.addFilter(_FILTER)

    if _installed:
        return
    previous = logging.getLogRecordFactory()

    def factory(*args, **kwargs) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        _FILTER.filter(record)
        return record

    logging.setLogRecordFactory(factory)
    _installed = True
