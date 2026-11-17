"""Read the sanctions lists and screen a name against them.

The lists are published as files, not as an API, and they are large. This module
downloads each configured source once per run, reads it as JSON or CSV, and
hands the names to ``processing/sanctions.py`` with the source that produced
them — a match must be traceable to a list and an edition.

The format is read leniently on purpose: a JSON array of strings, a JSON array of
objects carrying a name and aliases, or a CSV whose header names a name column.
Anything else is treated as an unreadable source, which suspends the screening
instead of clearing the name.
"""

import csv
import io
import json
import logging

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from config import settings
from processing.sanctions import SanctionsList, SanctionsScreening
from processing.sanctions import screen as screen_with

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 60

# The names the lists use for the column that holds the entity's name.
_NAME_COLUMNS = ("sdn_name", "name", "caption", "entity", "full_name", "legal_name")
_ALIAS_COLUMNS = ("aliases", "alias", "aka", "aka_list", "other_names")

_USER_AGENT = "GTMTool/1.0 (sanctions screening; +https://example.invalid)"


class SanctionsError(RuntimeError):
    """The lists could not be read; the screening cannot conclude."""


def configured_sources() -> dict[str, str]:
    """The sources and their addresses, from ``SANCTIONS_LIST_URLS``."""
    raw = settings.SANCTIONS_LIST_URLS or ""
    sources: dict[str, str] = {}
    for part in raw.split(","):
        name, separator, url = part.partition("=")
        if separator and name.strip() and url.strip():
            sources[name.strip()] = url.strip()
    return sources


def is_configured() -> bool:
    return bool(configured_sources())


def parse_list(text: str, *, source: str) -> SanctionsList:
    """Read one list as JSON or CSV, keeping the names and aliases it holds."""
    text = (text or "").strip()
    if not text:
        raise SanctionsError(f"{source}: empty list")

    if text.startswith(("[", "{")):
        return SanctionsList(source, names=_json_names(text, source=source))

    return SanctionsList(source, names=_csv_names(text, source=source))


def load(fetch=None) -> SanctionsScreening:
    """Read every configured source; an unreadable one is reported, not ignored."""
    sources = configured_sources()
    if not sources:
        raise SanctionsError(
            "no sanctions list is configured: set SANCTIONS_LIST_URLS in .env"
        )

    fetch = fetch or http_get
    lists: list[SanctionsList] = []
    unavailable: list[str] = []

    for source, url in sources.items():
        try:
            text = fetch(url)
            if text is None:
                unavailable.append(source)
                continue
            lists.append(parse_list(text, source=source))
        except Exception as error:  # noqa: BLE001 - one source must not stop the others
            log.warning("Sanctions list %s unreadable: %s", source, error)
            unavailable.append(source)

    return SanctionsScreening(lists=tuple(lists), unavailable=tuple(unavailable))


def screen(subject: str, *, aliases=(), fetch=None, screening=None):
    """Load the lists once and screen one name against them."""
    if screening is None:
        screening = load(fetch=fetch)
    return screen_with(subject, screening, aliases=aliases)


def http_get(url: str, *, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> str | None:
    """Download one list; None when it cannot be read after retries."""
    try:
        return _get_with_retry(url, timeout_seconds=timeout_seconds)
    except _Temporary as error:
        log.warning("Sanctions source unreachable: %s (%s)", url, error)
        return None


class _Temporary(SanctionsError):
    pass


@retry(
    retry=retry_if_exception_type(_Temporary),
    wait=wait_exponential_jitter(initial=1, max=15),
    stop=stop_after_attempt(3),
    reraise=True,
)
def _get_with_retry(url: str, *, timeout_seconds: int) -> str | None:
    client = httpx.Client(
        timeout=httpx.Timeout(timeout_seconds, connect=10.0),
        follow_redirects=True,
        headers={"User-Agent": _USER_AGENT},
    )
    try:
        response = client.get(url)
    except httpx.TransportError as error:
        raise _Temporary(type(error).__name__) from error
    finally:
        client.close()

    if response.status_code == 429 or response.status_code >= 500:
        raise _Temporary(f"HTTP {response.status_code}")
    if response.status_code >= 400:
        log.warning("Sanctions source refused: %s (HTTP %s)", url, response.status_code)
        return None
    return response.text


def _json_names(text: str, *, source: str) -> tuple[str, ...]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise SanctionsError(f"{source}: invalid JSON") from error

    rows = payload if isinstance(payload, list) else payload.get("entries", [])
    names: list[str] = []
    for row in rows:
        if isinstance(row, str):
            names.append(row)
            continue
        if not isinstance(row, dict):
            continue
        for key, value in row.items():
            if key.lower() in _ALIAS_COLUMNS or key.lower() in _NAME_COLUMNS:
                names.extend(_as_names(value))
    return _unique(names)


def _csv_names(text: str, *, source: str) -> tuple[str, ...]:
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        raise SanctionsError(f"{source}: empty CSV")

    header = [cell.strip().lower() for cell in rows[0]]
    name_index = next(
        (header.index(column) for column in _NAME_COLUMNS if column in header), None
    )
    alias_indexes = [
        index for index, column in enumerate(header) if column in _ALIAS_COLUMNS
    ]

    if name_index is None:
        # No usable header: assume the first column holds the name, and skip the
        # first row only when it looks like a header.
        body = rows[1:] if _looks_like_a_header(rows[0]) else rows
        return _unique(row[0].strip() for row in body if row and row[0].strip())

    names: list[str] = []
    for row in rows[1:]:
        if len(row) > name_index:
            names.extend(_as_names(row[name_index]))
        for index in alias_indexes:
            if len(row) > index:
                names.extend(_as_names(row[index]))
    return _unique(names)


def _looks_like_a_header(row) -> bool:
    return any(cell.strip().lower() in _NAME_COLUMNS for cell in row)


def _as_names(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    # CSV alias cells often hold several names separated by a semicolon.
    return [part.strip() for part in text.split(";") if part.strip()]


def _unique(names) -> tuple[str, ...]:
    """Keep the spelling of each name, drop the repeats by folded key."""
    seen: set[str] = set()
    kept: list[str] = []
    for name in names:
        text = " ".join(str(name).split())
        key = text.casefold()
        if key and key not in seen:
            seen.add(key)
            kept.append(text)
    return tuple(kept)
