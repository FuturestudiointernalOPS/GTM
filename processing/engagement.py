"""Engagement measure: the median reach of one item, per platform.

Implements ``docs/engagement.md`` (rules M-01 to M-10). The result carries the
median, the sample it was computed on and the flags that qualify it; it does not
carry a ratio or points, which belong to ``processing/scoring.py``.

The function is pure: a sample in, a measure out. No network, no clock, no model.
The same snapshot always yields the same median and the same hash.
"""
import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from fractions import Fraction

MEASURED = "MEASURED"
UNKNOWN = "UNKNOWN"

TIME = "TIME"
FALLBACK = "FALLBACK"

MEDIAN = "MEDIAN"
VIEWS_PER_ITEM = "VIEWS_PER_ITEM"
CONCURRENT_VIEWERS = "CONCURRENT_VIEWERS"

WEAK_SAMPLE = "WEAK_SAMPLE"
WINDOW_EXTENDED = "WINDOW_EXTENDED"
DISPERSION = "DISPERSION"
UNREADABLE = "UNREADABLE"

# M-04: the fallback keeps the ten most recent items of the wider window.
FALLBACK_ITEMS = 10

# M-05: at least five readable items; five to nine carry WEAK_SAMPLE.
MIN_READABLE = 5
WEAK_UP_TO = 9

# Structural exclusions (M-06). An unreadable item is counted, not dropped
# silently: it is removed from the median but appears in unreadable_count.
_STRUCTURAL_EXCLUSIONS = frozenset({"PINNED", "PAID_AD", "CLIP", "LIVE"})
_UNREADABLE_REASON = "UNREADABLE"

_KNOWN_KINDS = frozenset(
    {"POST", "LONG_VIDEO", "SHORT", "STREAM", "VOD", "CLIP"}
)
_KNOWN_EXCLUSIONS = frozenset(
    {"PINNED", "PAID_AD", "CLIP", "LIVE", "UNREADABLE"}
)


@dataclass(frozen=True)
class Policy:
    """Which items count on a platform, and over which windows."""

    kinds: frozenset[str]
    window_days: int
    max_items: int
    fallback_days: int | None
    measure_kind: str = VIEWS_PER_ITEM


POLICIES = {
    "telegram": Policy(frozenset({"POST"}), 30, 30, 90),
    "vk_video": Policy(frozenset({"LONG_VIDEO"}), 30, 30, 90),
    "rutube": Policy(frozenset({"LONG_VIDEO"}), 30, 30, 90),
    "youtube": Policy(frozenset({"LONG_VIDEO"}), 30, 30, 180),
    # Twitch measures live concurrency; replays are never a fallback (M-06).
    "twitch": Policy(frozenset({"STREAM"}), 60, 10, None, CONCURRENT_VIEWERS),
}


@dataclass(frozen=True)
class EngagementItem:
    """One publication, video or stream, read at the snapshot time."""

    platform: str
    item_url: str
    item_kind: str
    published_at: str
    value: int | Fraction | None
    read_at: str
    readable: bool = True
    exclusion_reason: str | None = None
    item_id: str | None = None


@dataclass(frozen=True)
class EngagementProfile:
    """The account the sample belongs to."""

    main_platform: str
    followers: int
    followers_read_at: str


@dataclass(frozen=True)
class EngagementMeasure:
    """The documented output of the measure (see engagement.md §3)."""

    status: str
    measure_kind: str | None
    statistic: str
    value: Fraction | None
    sample_size: int
    unreadable_count: int
    window_start: str | None
    window_end: str | None
    window_mode: str | None
    flags: tuple[str, ...]
    read_at: str | None
    sample_hash: str
    reason: str | None = None  # diagnostic only; never a criterion


def measure_engagement(
    items: Iterable[EngagementItem], profile: EngagementProfile
) -> EngagementMeasure:
    """Turn one snapshot into a median, or refuse to measure (M-07)."""
    platform = platform_key(profile.main_platform)
    policy = POLICIES.get(platform)
    if policy is None:
        return _unknown(
            measure_kind=None,
            reason="platform_without_policy",
            read_at=_profile_read_at(profile),
        )

    sample = [item for item in items if platform_key(item.platform) == platform]
    if not sample:
        return _unknown(
            measure_kind=policy.measure_kind,
            reason="empty_sample",
            read_at=_profile_read_at(profile),
        )

    for item in sample:
        _validate_item(item)

    relevant = [item for item in sample if _is_relevant(item, policy)]
    if not relevant:
        return _unknown(
            measure_kind=policy.measure_kind,
            reason="empty_sample",
            read_at=_profile_read_at(profile),
        )

    snapshot = _snapshot(relevant, profile)
    if snapshot is None:
        return _unknown(
            measure_kind=policy.measure_kind,
            reason="snapshot_mismatch",
            read_at=_profile_read_at(profile),
        )

    mode = TIME
    start = snapshot - timedelta(days=policy.window_days)
    main = _window(sample, snapshot, policy.window_days, policy.max_items, policy)
    candidates, unreadable, readable = main

    if _has_out_of_domain(candidates):
        return _refuse_window(
            measure_kind=policy.measure_kind,
            reason="out_of_domain",
            snapshot=snapshot,
            start=start,
            mode=mode,
            readable=readable,
            unreadable=unreadable,
        )

    if _mostly_unreadable(main):
        return _refuse_window(
            measure_kind=policy.measure_kind,
            reason="mostly_unreadable",
            snapshot=snapshot,
            start=start,
            mode=mode,
            readable=readable,
            unreadable=unreadable,
        )

    if len(readable) < MIN_READABLE and policy.fallback_days is not None:
        mode = FALLBACK
        start = snapshot - timedelta(days=policy.fallback_days)
        fallback = _window(
            sample, snapshot, policy.fallback_days, FALLBACK_ITEMS, policy
        )
        candidates, unreadable, readable = fallback

        if _has_out_of_domain(candidates):
            return _refuse_window(
                measure_kind=policy.measure_kind,
                reason="out_of_domain",
                snapshot=snapshot,
                start=start,
                mode=mode,
                readable=readable,
                unreadable=unreadable,
            )

        if _mostly_unreadable(fallback):
            return _refuse_window(
                measure_kind=policy.measure_kind,
                reason="mostly_unreadable",
                snapshot=snapshot,
                start=start,
                mode=mode,
                readable=readable,
                unreadable=unreadable,
            )

    if len(readable) < MIN_READABLE:
        return _refuse_window(
            measure_kind=policy.measure_kind,
            reason="sample_too_small",
            snapshot=snapshot,
            start=start,
            mode=mode,
            readable=readable,
            unreadable=unreadable,
        )

    values = [Fraction(item.value) for item in readable]
    value = _median(values)
    dispersion = sum(values) / len(values) > 2 * value

    return EngagementMeasure(
        status=MEASURED,
        measure_kind=policy.measure_kind,
        statistic=MEDIAN,
        value=value,
        sample_size=len(readable),
        unreadable_count=len(unreadable),
        window_start=_stamp(start),
        window_end=_stamp(snapshot),
        window_mode=mode,
        flags=_quality_flags(
            sample_size=len(readable),
            unreadable_count=len(unreadable),
            mode=mode,
            dispersion=dispersion,
        ),
        read_at=_stamp(snapshot),
        sample_hash=_hash(readable),
    )


def _window(
    sample: list[EngagementItem],
    snapshot: datetime,
    days: int,
    max_items: int,
    policy: Policy,
) -> tuple[list[EngagementItem], list[EngagementItem], list[EngagementItem]]:
    """Return (candidates, unreadable, readable) for one window.

    The platform's types are selected first, then the most recent ``max_items``
    are kept, then structural exclusions are removed. A pinned post therefore
    consumes one of the slots and does not allow a 31st item to enter (M10).
    """
    floor = snapshot - timedelta(days=days)
    in_window = []
    for item in sample:
        if _kind(item) not in policy.kinds:
            continue
        published = _published(item)
        if published is None:
            continue
        if floor <= published <= snapshot:
            in_window.append((published, item))

    in_window.sort(
        key=lambda pair: (
            pair[0],
            pair[1].item_url or "",
            pair[1].item_id or "",
        ),
        reverse=True,
    )
    kept = [item for _, item in in_window[:max_items]]

    candidates = [
        item for item in kept if _reason(item) not in _STRUCTURAL_EXCLUSIONS
    ]
    unreadable = [item for item in candidates if not _is_readable(item)]
    readable = [item for item in candidates if _is_readable(item)]
    return candidates, unreadable, readable


def _is_readable(item: EngagementItem) -> bool:
    return bool(
        item.readable
        and item.item_url
        and item.value is not None
        and _reason(item) != _UNREADABLE_REASON
    )


def _mostly_unreadable(window) -> bool:
    candidates, unreadable, _ = window
    return len(unreadable) * 2 > len(candidates)


def _median(values: list[Fraction]) -> Fraction:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _snapshot(
    relevant: list[EngagementItem], profile: EngagementProfile
) -> datetime | None:
    """One snapshot means one timestamp for relevant items and followers (M-03)."""
    stamps = {_parse(item.read_at) for item in relevant}
    followers_stamp = _parse(profile.followers_read_at)
    if None in stamps or followers_stamp is None or len(stamps) != 1:
        return None
    (stamp,) = stamps
    if stamp != followers_stamp:
        return None
    return stamp


def _published(item: EngagementItem) -> datetime | None:
    return _parse(item.published_at)


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _stamp(value: datetime) -> str:
    """One canonical representation, so equal instants hash the same."""
    return value.astimezone(UTC).isoformat()


def _hash(items: list[EngagementItem]) -> str:
    rows = []
    for item in items:
        published = _parse(item.published_at)
        rows.append(
            "|".join(
                (
                    platform_key(item.platform) or item.platform,
                    item.item_id or "",
                    item.item_url or "",
                    _kind(item),
                    _stamp(published) if published else item.published_at,
                    str(item.value),
                )
            )
        )
    return hashlib.sha256("\n".join(sorted(rows)).encode("utf-8")).hexdigest()[:16]


def platform_key(platform: str | None) -> str | None:
    """Normalize a platform label to the key used by the policies."""
    if not platform:
        return None
    key = platform.strip().lower().replace("-", " ").replace("_", " ")
    key = "_".join(key.split())
    return {"vk": "vk_video", "vkvideo": "vk_video", "vk_video_live": "vk_video"}.get(
        key, key
    )


def _kind(item: EngagementItem) -> str:
    return (item.item_kind or "").strip().upper()


def _reason(item: EngagementItem) -> str | None:
    reason = (item.exclusion_reason or "").strip().upper()
    return reason or None


def _is_relevant(item: EngagementItem, policy: Policy) -> bool:
    return _kind(item) in policy.kinds and _reason(item) not in _STRUCTURAL_EXCLUSIONS


def _validate_item(item: EngagementItem) -> None:
    if _kind(item) not in _KNOWN_KINDS:
        raise ValueError(f"unknown engagement item kind: {item.item_kind!r}")
    reason = _reason(item)
    if reason is not None and reason not in _KNOWN_EXCLUSIONS:
        raise ValueError(
            f"unknown engagement exclusion reason: {item.exclusion_reason!r}"
        )
    if item.value is not None and (
        isinstance(item.value, bool)
        or not isinstance(item.value, (int, Fraction))
    ):
        raise ValueError(
            "an engagement value must be an integer, a Fraction, or None"
        )


def _has_out_of_domain(candidates: list[EngagementItem]) -> bool:
    return any(
        item.readable
        and item.value is not None
        and item.value < 0
        and _reason(item) != _UNREADABLE_REASON
        for item in candidates
    )


def _quality_flags(
    *,
    sample_size: int,
    unreadable_count: int,
    mode: str,
    dispersion: bool = False,
) -> tuple[str, ...]:
    flags = []
    if MIN_READABLE <= sample_size <= WEAK_UP_TO:
        flags.append(WEAK_SAMPLE)
    if mode == FALLBACK:
        flags.append(WINDOW_EXTENDED)
    if dispersion:
        flags.append(DISPERSION)
    if unreadable_count:
        flags.append(UNREADABLE)
    return tuple(flags)


def _profile_read_at(profile: EngagementProfile) -> str | None:
    parsed = _parse(profile.followers_read_at)
    return _stamp(parsed) if parsed else None


def _refuse_window(
    *,
    measure_kind: str,
    reason: str,
    snapshot: datetime,
    start: datetime,
    mode: str,
    readable: list[EngagementItem],
    unreadable: list[EngagementItem],
) -> EngagementMeasure:
    return _unknown(
        measure_kind=measure_kind,
        reason=reason,
        read_at=_stamp(snapshot),
        sample_size=len(readable),
        unreadable_count=len(unreadable),
        window_start=_stamp(start),
        window_end=_stamp(snapshot),
        window_mode=mode,
        flags=_quality_flags(
            sample_size=len(readable),
            unreadable_count=len(unreadable),
            mode=mode,
        ),
        sample_hash=_hash(readable),
    )


def _unknown(
    *,
    measure_kind: str | None,
    reason: str,
    read_at: str | None = None,
    sample_size: int = 0,
    unreadable_count: int = 0,
    window_start: str | None = None,
    window_end: str | None = None,
    window_mode: str | None = None,
    flags: tuple[str, ...] = (),
    sample_hash: str | None = None,
) -> EngagementMeasure:
    return EngagementMeasure(
        status=UNKNOWN,
        measure_kind=measure_kind,
        statistic=MEDIAN,
        value=None,
        sample_size=sample_size,
        unreadable_count=unreadable_count,
        window_start=window_start,
        window_end=window_end,
        window_mode=window_mode,
        flags=flags,
        read_at=read_at,
        sample_hash=sample_hash if sample_hash is not None else _hash([]),
        reason=reason,
    )
