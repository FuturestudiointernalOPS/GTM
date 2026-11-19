"""Search the Roskomnadzor registry for one creator page.

The registry is a public web form, not an API. Three things follow from that,
and they shape this module:

* the endpoint and the name of the field carrying the query are **configuration**
  (`RKN_SEARCH_URL`, `RKN_QUERY_FIELD`), not code — the form can change under us,
  and a hard-coded endpoint would fail silently;
* the answer is HTML. ``parse_rows`` is deliberately generic: it reads table rows
  and keeps every link of a row, because the page address is not necessarily in
  the column a guess would pick;
* a page nobody can read is not an absence. A transport failure, a refused form
  or a page with no result table at all makes the search **unavailable**, which
  the comparison turns into ``PENDING`` — never ``NOT_FOUND``, which would accuse
  a page of not being registered.

The search by address alone is one of the two paths allowed by §2.2, and it is
the one this service can always run: ``platform_url`` is the mandatory key of a
profile (§2.5).
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from config import settings
from processing.eligibility import Check
from processing.rkn import RegistryEntry, RegistrySearch, compare

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 20

# A result table never needs this many rows; the cap bounds what one answer can
# cost to compare.
MAX_ENTRIES = 50

_USER_AGENT = "GTMTool/1.0 (registry check; +https://example.invalid)"


class RknError(RuntimeError):
    """The registry search failed; repeating it unchanged will not help."""


class RknTemporaryError(RknError):
    """Rate limit, server problem or network down; retrying may succeed."""


class RknNotConfigured(RknError):
    """The endpoint or the form field is not set in the settings."""


@dataclass(frozen=True)
class SearchPage:
    """One answer of the service, as text, with the address that produced it."""

    html: str
    url: str = ""
    status: int | None = None


# What a caller may inject: a fetch returning None when the service cannot be
# read, and a parser reading one answer into rows.
Fetcher = Callable[[str], SearchPage | None]
Parser = Callable[..., tuple[RegistryEntry, ...]]


def is_configured() -> bool:
    """True when the endpoint and the form field are set."""
    return bool(settings.RKN_SEARCH_URL and settings.RKN_QUERY_FIELD)


def allowed_domains() -> tuple[str, ...]:
    """The official hosts, from the comma-separated setting."""
    raw = settings.RKN_ALLOWED_DOMAINS or ""
    return tuple(
        domain.strip().lower().removeprefix("www.")
        for domain in raw.split(",")
        if domain.strip()
    )


def search(
    query: str, *, fetch: Fetcher | None = None, parser: Parser | None = None
) -> RegistrySearch:
    """Search the registry by page address, and return the rows it lists.

    ``fetch`` and ``parser`` are injectable so a test needs no network; leaving
    ``fetch`` empty uses the configured form, and refuses with a clear message
    when it is not configured.
    """
    text = (query or "").strip()
    if not text:
        raise ValueError("the registry search needs a query")
    read = parser or parse_rows

    if fetch is None:
        if not is_configured():
            raise RknNotConfigured(
                "the registry form is not configured: set RKN_SEARCH_URL and "
                "RKN_QUERY_FIELD in the .env file"
            )
        fetch = http_fetch

    page = fetch(text)
    if page is None:
        return RegistrySearch(query=text, unavailable=True)

    entries = tuple(read(page.html, base_url=page.url))[:MAX_ENTRIES]
    if not entries and not _looks_like_a_result_page(page.html):
        # We did not understand the answer. Saying "no entry" here would make an
        # unrecognised page look like an unregistered creator.
        log.warning("RKN answer unreadable for %s: no result table", text)
        return RegistrySearch(query=text, unavailable=True)

    official = allowed_domains()
    lookalike = bool(official) and _host(page.url) not in official
    log.info("RKN search for %s: %s row(s)", text, len(entries))
    return RegistrySearch(query=text, entries=entries, lookalike=lookalike)


def check(
    page_url: str,
    *,
    account_id: str | None = None,
    display_name: str | None = None,
    fetch: Fetcher | None = None,
    parser: Parser | None = None,
) -> Check:
    """Search the registry for one page and return the check it proves.

    One call for the whole path: the address goes to the form, the answer is
    read into rows, and the rows are compared with the page. The result feeds
    `CreatorVerification.rkn_status` and its reasons.
    """
    found = search(page_url, fetch=fetch, parser=parser)
    return compare(page_url, found, account_id=account_id, display_name=display_name)


def parse_rows(html: str, *, base_url: str = "") -> tuple[RegistryEntry, ...]:
    """Read every table row into one entry.

    A row keeps every address it links: the registry card is on the service's
    host, the creator's page is on the platform, and neither position is
    guaranteed. The card gives the name and, when the address ends with a number,
    the technical identifier (§2.5).
    """
    soup = BeautifulSoup(html, "html.parser")
    official = allowed_domains()
    entries: list[RegistryEntry] = []

    for row in soup.find_all("tr"):
        anchors = [
            (anchor, _absolute(anchor["href"], base_url))
            for anchor in row.find_all("a", href=True)
            if anchor["href"].strip()
        ]
        if not anchors:
            continue

        card = next(
            ((anchor, url) for anchor, url in anchors if _host(url) in official),
            None,
        )
        addresses = tuple(url for _, url in anchors if card is None or url != card[1])
        if not addresses and card is not None:
            addresses = (card[1],)

        entries.append(
            RegistryEntry(
                urls=addresses,
                name=(card[0] if card else anchors[0][0]).get_text(" ", strip=True),
                account_id=_identifier(card[1]) if card else None,
            )
        )

    return tuple(entries)


def http_fetch(
    query: str, *, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
) -> SearchPage | None:
    """Post the form and read the answer; None when it cannot be read."""
    try:
        return _fetch_with_retry(query, timeout_seconds=timeout_seconds)
    except RknTemporaryError as error:
        log.warning("RKN unavailable for %s (%s)", query, error)
        return None


@retry(
    retry=retry_if_exception_type(RknTemporaryError),
    wait=wait_exponential_jitter(initial=1, max=10),
    stop=stop_after_attempt(3),
    reraise=True,
)
def _fetch_with_retry(query: str, *, timeout_seconds: int) -> SearchPage | None:
    timeout = httpx.Timeout(timeout_seconds, connect=5.0)
    client = httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": _USER_AGENT},
    )
    try:
        response = client.post(settings.RKN_SEARCH_URL, data=_form_data(query))
    except httpx.TransportError as error:
        raise RknTemporaryError(type(error).__name__) from error
    finally:
        client.close()

    if response.status_code == 429 or response.status_code >= 500:
        raise RknTemporaryError(f"HTTP {response.status_code}")
    if response.status_code >= 400:
        # A changed form answers 400 or 404: retrying will not help, and the
        # search is unreadable, not empty.
        log.warning("RKN refused the search: HTTP %s", response.status_code)
        return None

    return SearchPage(
        html=response.text, url=str(response.url), status=response.status_code
    )


def _form_data(query: str) -> dict:
    field = settings.RKN_QUERY_FIELD
    if not field:
        raise RknNotConfigured(
            "RKN_QUERY_FIELD is not set: the form field carrying the address"
        )
    return {field: query}


def _looks_like_a_result_page(html: str) -> bool:
    """True when the answer at least carries a result table."""
    lowered = (html or "").lower()
    return "<table" in lowered or "<tr" in lowered


def _absolute(href: str, base_url: str) -> str:
    href = href.strip()
    return urljoin(base_url, href) if base_url else href


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def _identifier(url: str) -> str | None:
    """The technical identifier, when the card address ends with one."""
    last = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
    return last if last.isdigit() else None
