"""Rebuild and qualify an engagement measure from stored sample rows (E5).

The fiche keeps the sample; this module lets a reviewer replay the exact measure
without opening the platform. It also mirrors the review/audit vocabulary used
by the SQL views, so the workflow and the database agree on what needs a human.

Nothing here reads a page or a clock: rows in, measure out.
"""

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from decimal import Decimal
from fractions import Fraction

from processing.engagement import (
    MEASURED,
    EngagementItem,
    EngagementMeasure,
    EngagementProfile,
    measure_engagement,
)

REVIEW_UNKNOWN = "UNKNOWN"
REVIEW_UNREADABLE = "UNREADABLE"
REVIEW_WEAK_SAMPLE = "WEAK_SAMPLE"
AUDIT_DISPERSION = "DISPERSION"


def item_from_row(row: Mapping, *, platform: str) -> EngagementItem:
    """Turn one stored sample row into the canonical measure input."""
    return EngagementItem(
        platform=platform,
        item_url=_text(row.get("item_url")) or "",
        item_kind=_text(row.get("item_kind")) or "",
        published_at=_stamp(row.get("published_at")) or "",
        value=_value(row.get("value")),
        read_at=_stamp(row.get("read_at")) or "",
        readable=bool(row.get("readable", True)),
        exclusion_reason=_text(row.get("exclusion_reason")),
        item_id=_text(row.get("item_id") or row.get("sample_id")),
    )


def recompute_measure(
    rows: Iterable[Mapping],
    *,
    platform: str,
    followers: int,
    read_at: str | datetime,
) -> EngagementMeasure:
    """Replay the measure from the stored sample, with the same rules.

    The caller supplies the profile's follower count and snapshot time; the
    sample rows supply the items. A row list that is not the run's snapshot will
    produce ``snapshot_mismatch`` rather than a misleading median.
    """
    stamp = _stamp(read_at)
    if stamp is None:
        raise ValueError("read_at must be a datetime or an ISO string")
    items = [item_from_row(row, platform=platform) for row in rows]
    return measure_engagement(
        items,
        EngagementProfile(
            main_platform=platform,
            followers=followers,
            followers_read_at=stamp,
        ),
    )


def review_reasons(measure: EngagementMeasure) -> tuple[str, ...]:
    """The reasons a human must look at the measure, in the SQL view's order."""
    if measure.status != MEASURED:
        return (REVIEW_UNKNOWN,)
    reasons = []
    if "UNREADABLE" in measure.flags:
        reasons.append(REVIEW_UNREADABLE)
    if "WEAK_SAMPLE" in measure.flags:
        reasons.append(REVIEW_WEAK_SAMPLE)
    return tuple(reasons)


def needs_audit(measure: EngagementMeasure) -> bool:
    """Dispersion is an audit signal; it never changes the points."""
    return AUDIT_DISPERSION in measure.flags


def matches_stored(measure: EngagementMeasure, *, status: str, value: object) -> bool:
    """True when a replay agrees with the stored status and median."""
    if measure.status != status:
        return False
    if measure.value is None:
        return value is None
    if value is None:
        return False
    try:
        return Fraction(str(value)) == measure.value
    except (TypeError, ValueError, ZeroDivisionError):
        return False


def _stamp(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC).isoformat()
    text = str(value).strip()
    return text or None


def _value(value) -> int | Fraction | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, Fraction)):
        return value
    if isinstance(value, Decimal):
        return Fraction(value)
    if isinstance(value, float):
        return Fraction(str(value))
    text = str(value).strip()
    if not text:
        return None
    try:
        return Fraction(text)
    except (ValueError, ZeroDivisionError):
        return None


def _text(value) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None
