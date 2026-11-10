"""Web search through Exa.

Why Exa: it answers "which public pages talk about this company or creator"
without us writing a crawler. It returns URLs, titles and dates; Apify then
extracts structured rows from the pages that matter.

A row returned here is a lead, not a proof. The workflow still has to attach
the source and check the page before the fact enters a record (scope §3.1).
"""
import logging
import re
from collections.abc import Sequence

from exa_py import Exa
from exa_py.errors import ExaTimeoutError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from config import settings

log = logging.getLogger(__name__)

DEFAULT_RESULTS = 10

# Exa refuses more than 100 results in one request.
MAX_RESULTS = 100

# Text is billed and makes answers heavy; 2000 characters are enough to decide
# whether a page is relevant.
DEFAULT_TEXT_CHARACTERS = 2000


class ExaError(RuntimeError):
    """The search was refused; repeating it unchanged will not help."""


class ExaTemporaryError(ExaError):
    """Rate limit, server problem or network down; retrying may succeed."""


class ExaNotConfigured(ExaError):
    """No API key: the settings were not filled in."""


def is_configured() -> bool:
    """True when an Exa API key is set."""
    return bool(settings.EXA_API_KEY)


def search(
    query: str,
    *,
    num_results: int = DEFAULT_RESULTS,
    include_domains: Sequence[str] | None = None,
    exclude_domains: Sequence[str] | None = None,
    include_text: Sequence[str] | None = None,
    exclude_text: Sequence[str] | None = None,
    start_published_date: str | None = None,
    category: str | None = None,
    with_text: bool = False,
    max_characters: int = DEFAULT_TEXT_CHARACTERS,
) -> list[dict]:
    """Search the web and return a stable list of rows.

    Only the options that are actually set are sent, so Exa keeps its own
    defaults for everything else. ``start_published_date`` uses the ISO form
    ``YYYY-MM-DD``. ``category`` is Exa's category, for example ``company`` or
    ``people``. ``include_text`` and ``exclude_text`` restrict the page text;
    they replace the ``+`` and ``-`` operators that Exa does not support.

    Each row always has the same keys: ``url``, ``title``, ``published_date``,
    ``author`` and ``text`` (``None`` unless ``with_text`` is true). Missing
    values are ``None`` instead of being dropped, so downstream schemas do not
    have to guess.
    """
    if not query or not query.strip():
        raise ValueError("Exa query must not be empty")
    if not 1 <= num_results <= MAX_RESULTS:
        raise ValueError(f"num_results must be between 1 and {MAX_RESULTS}")

    if not is_configured():
        raise ExaNotConfigured(
            "Exa is not configured: set EXA_API_KEY in the .env file"
        )

    options = {"num_results": num_results}
    if include_domains:
        options["include_domains"] = list(include_domains)
    if exclude_domains:
        options["exclude_domains"] = list(exclude_domains)
    if include_text:
        options["include_text"] = list(include_text)
    if exclude_text:
        options["exclude_text"] = list(exclude_text)
    if start_published_date:
        options["start_published_date"] = start_published_date
    if category:
        options["category"] = category
    if with_text:
        options["contents"] = {"text": {"max_characters": max_characters}}

    return _search_with_retry(query=query, options=options, with_text=with_text)


@retry(
    retry=retry_if_exception_type(ExaTemporaryError),
    wait=wait_exponential_jitter(initial=1, max=20),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _search_with_retry(query: str, options: dict, with_text: bool) -> list[dict]:
    client = Exa(api_key=settings.EXA_API_KEY)
    try:
        response = client.search(query, **options)
    except Exception as error:
        # The SDK does not expose one exception type per HTTP status, so the
        # translation happens here: workflows only ever see ExaError.
        raise _translate(error) from error

    rows = [_as_row(result, with_text=with_text) for result in response.results]
    log.info("Exa returned %s result(s) for %r", len(rows), query)
    return rows


def _as_row(result, with_text: bool) -> dict:
    """Flatten one SDK result into the contract workflows rely on."""
    return {
        "url": getattr(result, "url", None),
        "title": getattr(result, "title", None),
        "published_date": getattr(result, "published_date", None),
        "author": getattr(result, "author", None),
        "text": getattr(result, "text", None) if with_text else None,
    }


def _translate(error: Exception) -> ExaError:
    """Turn any SDK or transport failure into an ExaError."""
    status = _status_code(error)
    temporary = (
        status == 429
        or (status is not None and status >= 500)
        or _is_transport_error(error)
    )
    detail = f"HTTP {status}" if status is not None else type(error).__name__
    if temporary:
        return ExaTemporaryError(f"Exa is temporarily unavailable ({detail})")
    return ExaError(f"Exa refused the search ({detail}): {_short(error)}")


# The sync Exa client uses Requests, the async one HTTPX. Matching on the class
# name avoids importing Requests directly (forbidden by requirements.txt) and
# still recognizes both stacks.
_TRANSPORT_NAMES = {
    "Timeout",
    "ReadTimeout",
    "ConnectTimeout",
    "ConnectionError",
    "TransportError",
    "RemoteProtocolError",
}


def _is_transport_error(error: Exception) -> bool:
    return isinstance(error, ExaTimeoutError) or any(
        kind.__name__ in _TRANSPORT_NAMES for kind in type(error).__mro__
    )


def _status_code(error: Exception) -> int | None:
    """Read an HTTP status from the SDK, which only puts it in the message."""
    status = getattr(error, "status_code", None)
    if isinstance(status, int):
        return status
    match = re.search(r"status code (\d{3})", str(error))
    return int(match.group(1)) if match else None


def _short(error: Exception, limit: int = 300) -> str:
    """Keep error messages readable and bounded in a log line."""
    text = str(error).strip()
    return text if len(text) <= limit else f"{text[:limit]}..."
