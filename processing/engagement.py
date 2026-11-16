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
    sample_hash: str | None
    reason: str | None = None  # diagnostic only; never a criterion


def measure_engagement(
    items: Iterable[EngagementItem], profile: EngagementProfile
) -> EngagementMeasure:
    """Turn one snapshot into a median, or refuse to measure (M-07)."""
    platform = _platform_key(profile.main_platform)
    policy = POLICIES.get(platform)
    if policy is None:
        return _unknown(measure_kind=None, reason="platform_without_policy")

    sample = [item for item in items if _platform_key(item.platform) == platform]
    if not sample:
        return _unknown(measure_kind=policy.measure_kind, reason="empty_sample")

    snapshot = _snapshot(sample, profile)
    if snapshot is None:
        return _unknown(
            measure_kind=policy.measure_kind, reason="snapshot_mismatch"
        )

    main = _window(sample, snapshot, policy.window_days, policy.max_items, policy)
    if _mostly_unreadable(main):
        return _unknown(
            measure_kind=policy.measure_kind, reason="mostly_unreadable"
        )

    _, unreadable, readable = main
    mode = TIME
    start = snapshot - timedelta(days=policy.window_days)

    if len(readable) < MIN_READABLE and policy.fallback_days is not None:
        fallback = _window(
            sample, snapshot, policy.fallback_days, FALLBACK_ITEMS, policy
        )
        if _mostly_unreadable(fallback):
            return _unknown(
                measure_kind=policy.measure_kind, reason="mostly_unreadable"
            )
        _, unreadable, readable = fallback
        mode = FALLBACK
        start = snapshot - timedelta(days=policy.fallback_days)

    if len(readable) < MIN_READABLE:
        return _unknown(
            measure_kind=policy.measure_kind, reason="sample_too_small"
        )

    values = [Fraction(item.value) for item in readable]
    value = _median(values)

    flags = []
    if len(readable) <= WEAK_UP_TO:
        flags.append(WEAK_SAMPLE)
    if mode == FALLBACK:
        flags.append(WINDOW_EXTENDED)
    if unreadable:
        flags.append(UNREADABLE)
    if sum(values) / len(values) > 2 * value:
        flags.append(DISPERSION)

    return EngagementMeasure(
        status=MEASURED,
        measure_kind=policy.measure_kind,
        statistic=MEDIAN,
        value=value,
        sample_size=len(readable),
        unreadable_count=len(unreadable),
        window_start=start.isoformat(),
        window_end=snapshot.isoformat(),
        window_mode=mode,
        flags=tuple(flags),
        read_at=profile.followers_read_at,
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
    are kept, then structural exclusions are removed. A replay must not consume
    one of the ten Twitch slots, and a pinned post must not hide a publication.
    """
    floor = snapshot - timedelta(days=days)
    in_window = []
    for item in sample:
        if item.item_kind not in policy.kinds:
            continue
        published = _published(item)
        if published is None:
            continue
        if floor <= published <= snapshot:
            in_window.append((published, item))

    in_window.sort(key=lambda pair: pair[0], reverse=True)
    kept = [item for _, item in in_window[:max_items]]

    candidates = [
        item for item in kept if item.exclusion_reason not in _STRUCTURAL_EXCLUSIONS
    ]
    unreadable = [item for item in candidates if not _is_readable(item)]
    readable = [item for item in candidates if _is_readable(item)]
    return candidates, unreadable, readable


def _is_readable(item: EngagementItem) -> bool:
    if not item.readable or not item.item_url or item.value is None:
        return False
    return item.exclusion_reason != _UNREADABLE_REASON


def _mostly_unreadable(window) -> bool:
    candidates, unreadable, _ = window
    return len(unreadable) * 2 > len(candidates)


def _median(values: list[Fraction]) -> Fraction:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _snapshot(sample: list[EngagementItem], profile: EngagementProfile) -> datetime | None:
    """One snapshot means one timestamp for the items and the followers (M-03)."""
    stamps = {_parse(item.read_at) for item in sample}
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
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _hash(items: list[EngagementItem]) -> str:
    payload = "\n".join(
        sorted(
            f"{item.item_id or item.item_url}|{item.published_at}|{item.value}"
            for item in items
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _platform_key(platform: str | None) -> str | None:
    if not platform:
        return None
    key = platform.strip().lower().replace("-", " ").replace("_", " ")
    key = "_".join(key.split())
    return {"vk": "vk_video", "vkvideo": "vk_video", "vk_video_live": "vk_video"}.get(
        key, key
    )


def _unknown(*, measure_kind: str | None, reason: str) -> EngagementMeasure:
    return EngagementMeasure(
        status=UNKNOWN,
        measure_kind=measure_kind,
        statistic=MEDIAN,
        value=None,
        sample_size=0,
        unreadable_count=0,
        window_start=None,
        window_end=None,
        window_mode=None,
        flags=(),
        read_at=None,
        sample_hash=None,
        reason=reason,
    )
