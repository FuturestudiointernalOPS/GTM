"""Read a national betting-licence registry and check one company against it.

Every country publishes its own format, so this module fixes neither the URL nor
the shape of a registry: each country is one configured address returning a JSON
export of records. What is fixed is the refusal: a country without an address is
**not mapped**, and a registry that cannot be read **suspends** the
qualification (``REGULATORY_PENDING``) instead of rejecting anyone.

A document sent by the company is not read here; §3.6 and V-18 say it is not a
proof, and this client only reads official exports.
"""
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
from processing.licence import (
    LicenceCheck,
    LicenceRecord,
    LicenceRegistry,
)
from processing.licence import (
    check as check_with,
)

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 30

_USER_AGENT = "GTMTool/1.0 (licence check; +https://example.invalid)"


class LicenceError(RuntimeError):
    """The registry cannot be read, or the export is not what we expect."""


def configured_countries() -> dict[str, str]:
    """The mapped countries and their registry addresses, from the setting."""
    raw = settings.BETTING_LICENCE_URLS or ""
    countries: dict[str, str] = {}
    for part in raw.split(","):
        country, separator, url = part.partition("=")
        if separator and country.strip() and url.strip():
            countries[country.strip().upper()] = url.strip()
    return countries


def is_configured() -> bool:
    return bool(configured_countries())


def parse_registry(text: str, *, country: str, source_url: str | None = None) -> LicenceRegistry:
    """Read one JSON export into records.

    The export is a list of objects with at least ``number`` and ``holder``;
    ``activity``, ``status``, ``country`` and ``domains`` are kept when present.
    """
    try:
        payload = json.loads(text or "[]")
    except json.JSONDecodeError as error:
        raise LicenceError(f"{country}: invalid JSON export") from error

    rows = payload.get("records", []) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise LicenceError(f"{country}: the export is not a list of records")

    records: list[LicenceRecord] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        number = str(row.get("number") or "").strip()
        holder = str(row.get("holder") or "").strip()
        if not number or not holder:
            continue
        domains = row.get("domains") or row.get("official_domains") or ()
        if isinstance(domains, str):
            domains = (domains,)
        records.append(
            LicenceRecord(
                number=number,
                holder=holder,
                activity=_text(row.get("activity")),
                status=_text(row.get("status")),
                country=_text(row.get("country")) or country,
                domains=tuple(str(domain).strip() for domain in domains if domain),
            )
        )

    return LicenceRegistry(
        country=country, records=tuple(records), source_url=source_url
    )


def load(country: str, *, fetch=None) -> LicenceRegistry:
    """Read the registry of one country, or report why it cannot be read."""
    code = (country or "").strip().upper()
    addresses = configured_countries()
    if code not in addresses:
        # Not mapped is a policy state (§5), not a failure: it suspends.
        return LicenceRegistry(country=code, mapped=False)

    url = addresses[code]
    fetch = fetch or http_get
    try:
        text = fetch(url)
    except Exception as error:  # noqa: BLE001 - a registry is external data
        log.warning("Licence registry %s unreadable: %s", code, error)
        return LicenceRegistry(country=code, source_url=url, unavailable=True)

    if text is None:
        return LicenceRegistry(country=code, source_url=url, unavailable=True)

    try:
        return parse_registry(text, country=code, source_url=url)
    except LicenceError as error:
        log.warning("Licence registry %s unreadable: %s", code, error)
        return LicenceRegistry(country=code, source_url=url, unavailable=True)


def check(
    *,
    country: str,
    holder: str,
    number: str | None = None,
    allowed_activities=(),
    fetch=None,
    registry: LicenceRegistry | None = None,
) -> LicenceCheck:
    """Read one country's registry and check one company against it."""
    if registry is None:
        registry = load(country, fetch=fetch)
    return check_with(
        registry,
        number=number,
        holder=holder,
        allowed_activities=allowed_activities,
    )


def http_get(url: str, *, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> str | None:
    """Download one export; None when it cannot be read after retries."""
    try:
        return _get_with_retry(url, timeout_seconds=timeout_seconds)
    except _Temporary as error:
        log.warning("Licence registry unreachable: %s (%s)", url, error)
        return None


class _Temporary(LicenceError):
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
        log.warning("Licence registry refused: %s (HTTP %s)", url, response.status_code)
        return None
    return response.text


def _text(value) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None
