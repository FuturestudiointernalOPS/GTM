"""Classic search-engine results through SerpApi.

Why SerpApi: the supervisor's query pool is written for engines that understand
``site:``, quotes and ``-terms``, which Exa does not. SerpApi executes that
syntax on Google (and other engines) and returns the same row shape the
workflows already consume.

Security: the API key travels as a query parameter. It is never logged and
never copied into an error message; transport errors keep only their type, and
any echoed key is masked.
"""
import logging

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from config import settings

log = logging.getLogger(__name__)

API_ROOT = "https://serpapi.com/search.json"

DEFAULT_ENGINE = "google"
DEFAULT_LANGUAGE = "ru"
DEFAULT_COUNTRY = "ru"

# Google returns at most 100 organic results per query.
MAX_RESULTS = 100

TIMEOUT = httpx.Timeout(20.0, connect=5.0)


class SerpApiError(RuntimeError):
    """The search was refused; repeating it unchanged will not help."""


class SerpApiTemporaryError(SerpApiError):
    """Rate limit, server problem or network down; retrying may succeed."""


class SerpApiNotConfigured(SerpApiError):
    """No API key: the settings were not filled in."""


def is_configured() -> bool:
    """True when a SerpApi key is set."""
    return bool(settings.SERPAPI_API_KEY)


def search(
    query: str,
    *,
    engine: str = DEFAULT_ENGINE,
    num_results: int = 10,
    start: int = 0,
    language: str | None = DEFAULT_LANGUAGE,
    country: str | None = DEFAULT_COUNTRY,
    location: str | None = None,
) -> list[dict]:
    """Run one classic-engine query and return a stable list of rows.

    ``query`` keeps the operators the pool was written with: ``site:``,
    quotes and ``-terms``. ``engine`` is passed to SerpApi (``google`` by
    default; ``yandex`` and others exist but need their own settings).

    Russian results are the default (``hl=ru``, ``gl=ru``). Pass ``None`` to
    omit either parameter. SerpApi returns snippets, not page bodies, so
    ``text`` is always ``None`` and ``snippet`` carries the visible extract.
    """
    if not query or not query.strip():
        raise ValueError("SerpApi query must not be empty")
    if not engine or not engine.strip():
        raise ValueError("SerpApi engine must not be empty")
    if not 1 <= num_results <= MAX_RESULTS:
        raise ValueError(f"num_results must be between 1 and {MAX_RESULTS}")
    if start < 0:
        raise ValueError("start must be zero or positive")

    if not is_configured():
        raise SerpApiNotConfigured(
            "SerpApi is not configured: set SERPAPI_API_KEY in the .env file"
        )

    params: dict = {
        "engine": engine.strip(),
        "q": query.strip(),
        "num": num_results,
        "start": start,
    }
    if language:
        params["hl"] = language
    if country:
        params["gl"] = country
    if location:
        params["location"] = location.strip()

    return _search_with_retry(query=query, params=params)


@retry(
    retry=retry_if_exception_type(SerpApiTemporaryError),
    wait=wait_exponential_jitter(initial=1, max=20),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _search_with_retry(query: str, params: dict) -> list[dict]:
    client = httpx.Client(timeout=TIMEOUT)
    try:
        response = client.get(
            API_ROOT,
            params={**params, "api_key": settings.SERPAPI_API_KEY},
        )
    except httpx.TransportError as error:
        # The URL carries the key, so only the error type is kept.
        raise SerpApiTemporaryError(
            f"cannot reach SerpApi ({type(error).__name__})"
        ) from error
    finally:
        client.close()

    # 429 = rate limit, 5xx = SerpApi side: both are worth another attempt.
    if response.status_code == 429 or response.status_code >= 500:
        raise SerpApiTemporaryError(
            f"SerpApi answered {response.status_code}: {_error(response)}"
        )

    if response.status_code >= 400:
        raise SerpApiError(
            f"SerpApi refused the search ({response.status_code}): "
            f"{_error(response)}"
        )

    body = _body(response)
    if body.get("error"):
        raise SerpApiError(f"SerpApi refused the search: {_error(response)}")

    rows = [
        row
        for item in body.get("organic_results", [])
        if (row := _as_row(item)) is not None
    ]
    log.info("SerpApi returned %s result(s) for %r", len(rows), query)
    return rows


def _as_row(item: object) -> dict | None:
    """Flatten one organic result; skip anything without a URL."""
    if not isinstance(item, dict):
        return None
    url = _text(item.get("link"))
    if not url:
        return None
    return {
        "url": url,
        "title": _text(item.get("title")),
        "published_date": _text(item.get("date")),
        "author": None,
        "text": None,
        "snippet": _text(item.get("snippet")),
        "source": _text(item.get("source")),
        "position": item.get("position"),
    }


def _body(response: httpx.Response) -> dict:
    """Read SerpApi's JSON answer, or stop with a clear error."""
    try:
        body = response.json()
    except ValueError as error:
        raise SerpApiError("SerpApi answered with unreadable content") from error
    return body if isinstance(body, dict) else {}


def _error(response: httpx.Response) -> str:
    """SerpApi's own explanation, with any echoed key masked."""
    try:
        body = _body(response)
    except SerpApiError:
        # A proxy can answer 5xx with HTML; that must stay retryable.
        return "unreadable response"
    message = str(body.get("error") or "no reason")
    key = settings.SERPAPI_API_KEY
    return message.replace(key, "***") if key else message


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None
