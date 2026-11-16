"""Read candidate pages into clean text, one URL at a time.

Why separate from search: discovery returns short snippets; the next step reads
the pages that matter. A failure on one URL must not lose the batch, so each
URL is fetched and parsed independently and the result keeps a per-URL error.

Why BeautifulSoup: it strips the HTML and keeps the readable text, without a
headless browser. Dynamic or blocked pages are a platform problem and go to a
dedicated Actor instead.
"""
import logging
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

log = logging.getLogger(__name__)

DEFAULT_MAX_CHARS = 4000
DEFAULT_TIMEOUT_SECONDS = 15

# One batch stays small so a reading step has a bounded cost and latency.
MAX_URLS_PER_BATCH = 10

_USER_AGENT = "GTMTool/1.0 (contact collection; +https://example.invalid)"


@dataclass(frozen=True)
class PageRead:
    """The outcome of reading one URL: content, or a per-URL error."""

    url: str
    status: int | None = None
    title: str | None = None
    text: str | None = None
    error: str | None = None


class WebReaderError(RuntimeError):
    """A single page could not be read."""


class WebReaderTemporaryError(WebReaderError):
    """Network or server problem; retrying may succeed."""


def read_urls(
    urls,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> list[PageRead]:
    """Read every URL, isolating failures, and return one row per URL."""
    urls = [url.strip() for url in urls if url and url.strip()]
    if not urls:
        return []
    if len(urls) > MAX_URLS_PER_BATCH:
        raise ValueError(
            f"read_urls accepts at most {MAX_URLS_PER_BATCH} URLs per batch"
        )
    return [
        read_url(url, max_chars=max_chars, timeout_seconds=timeout_seconds)
        for url in urls
    ]


def read_url(
    url: str,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> PageRead:
    """Read one URL, returning a PageRead even when it fails."""
    try:
        return _read_with_retry(
            url,
            max_chars=max_chars,
            timeout_seconds=timeout_seconds,
        )
    except WebReaderError as error:
        log.warning("Page not read: %s (%s)", url, error)
        return PageRead(url=url, error=str(error))


@retry(
    retry=retry_if_exception_type(WebReaderTemporaryError),
    wait=wait_exponential_jitter(initial=1, max=10),
    stop=stop_after_attempt(3),
    reraise=True,
)
def _read_with_retry(
    url: str,
    *,
    max_chars: int,
    timeout_seconds: int,
) -> PageRead:
    timeout = httpx.Timeout(timeout_seconds, connect=5.0)
    client = httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": _USER_AGENT},
    )
    try:
        response = client.get(url)
    except httpx.TransportError as error:
        # The URL may carry tracking parameters, so keep only the error type.
        raise WebReaderTemporaryError(type(error).__name__) from error
    finally:
        client.close()

    if response.status_code == 429 or response.status_code >= 500:
        raise WebReaderTemporaryError(f"HTTP {response.status_code}")

    if response.status_code >= 400:
        return PageRead(url=url, status=response.status_code, error="http error")

    text = _extract_text(response.text, max_chars=max_chars)
    return PageRead(
        url=url,
        status=response.status_code,
        title=_title(response.text),
        text=text,
    )


def _extract_text(html: str, *, max_chars: int) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "head", "nav", "footer", "header", "noscript"]):
        tag.decompose()
    text = " ".join(soup.get_text(" ", strip=True).split())
    return text[:max_chars]


def _title(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    return None
