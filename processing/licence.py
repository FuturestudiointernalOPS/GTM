"""Compare a betting licence registry entry with the company being checked.

The registries differ from country to country, so this module does not fetch
anything: it applies §3.6 to records that were already read. Two confusions are
refused, because the scope insists on them:

* a **verified fact is not a favourable one** — a revoked licence is ``VERIFIED``
  and ineligible, not "verification failed";
* a licence **document** is not a licence — nothing here reads a PDF sent by the
  company (V-18).
"""
from dataclasses import dataclass

from processing.deduplication import normalize_legal_name
from processing.eligibility import (
    MISMATCH,
    NOT_FOUND,
    PENDING,
    VERIFIED,
)

ACTIVE = "ACTIVE"


@dataclass(frozen=True)
class LicenceRecord:
    """One line of a national registry."""

    number: str
    holder: str
    activity: str | None = None
    status: str | None = None
    country: str | None = None
    domains: tuple[str, ...] = ()


@dataclass(frozen=True)
class LicenceRegistry:
    """The registry of one country, as read."""

    country: str
    records: tuple[LicenceRecord, ...] = ()
    source_url: str | None = None
    unavailable: bool = False
    mapped: bool = True


@dataclass(frozen=True)
class LicenceCheck:
    """What the registry proves, and what it says about the licence itself."""

    status: str
    reasons: tuple[str, ...] = ()
    active: bool | None = None
    activity_allowed: bool | None = None
    country_mapped: bool = True
    source_url: str | None = None


def check(
    registry: LicenceRegistry,
    *,
    number: str | None = None,
    holder: str,
    allowed_activities=(),
) -> LicenceCheck:
    """Apply §3.6 to one registry: number first, holder as the cross-check.

    ``allowed_activities`` is what the campaign permits; empty means the
    question was not asked, and no incompatibility is claimed.
    """
    if not registry.mapped:
        return LicenceCheck(
            PENDING,
            ("COUNTRY_NOT_MAPPED",),
            country_mapped=False,
            source_url=registry.source_url,
        )
    if registry.unavailable:
        return LicenceCheck(
            PENDING, ("REGISTRY_UNAVAILABLE",), source_url=registry.source_url
        )

    record = _find(registry.records, number=number, holder=holder)
    if record is None:
        return LicenceCheck(
            NOT_FOUND, ("NO_LICENCE",), source_url=registry.source_url
        )

    if normalize_legal_name(record.holder) != normalize_legal_name(holder):
        return LicenceCheck(
            MISMATCH, ("HOLDER_MISMATCH",), source_url=registry.source_url
        )

    active = _is_active(record.status)
    reasons: list[str] = []
    if record.status:
        reasons.append(f"STATUS:{record.status}")
    if active is None:
        # The registry did not say. A licence whose status is unknown is not
        # verifiable, and a document is not a status (V-18, E-B-04).
        return LicenceCheck(
            PENDING, ("STATUS_UNKNOWN",), source_url=registry.source_url
        )
    if active is not True:
        # The fact is established; the licence simply does not permit anything.
        return LicenceCheck(
            VERIFIED,
            tuple(reasons),
            active=False,
            source_url=registry.source_url,
        )

    activity_allowed = _activity_allowed(record.activity, allowed_activities)
    if activity_allowed is False:
        reasons.append("ACTIVITY_NOT_ALLOWED")
    return LicenceCheck(
        VERIFIED,
        tuple(reasons),
        active=True,
        activity_allowed=activity_allowed,
        source_url=registry.source_url,
    )


def _find(records, *, number: str | None, holder: str) -> LicenceRecord | None:
    wanted = (number or "").strip()
    if wanted:
        for record in records:
            if (record.number or "").strip() == wanted:
                return record
        return None

    key = normalize_legal_name(holder)
    if key is None:
        return None
    for record in records:
        if normalize_legal_name(record.holder) == key:
            return record
    return None


def _is_active(status: str | None) -> bool | None:
    if not status:
        return None
    return status.strip().upper() == ACTIVE


def _activity_allowed(activity: str | None, allowed) -> bool | None:
    permits = {item.strip().casefold() for item in allowed if item and item.strip()}
    if not permits or not activity:
        return None
    return activity.strip().casefold() in permits
