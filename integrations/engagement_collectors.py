"""Turn platform rows into engagement samples.

Actors expose different field names and units. ``processing/engagement.py``
expects one canonical item: URL, kind, publication time, value, snapshot time,
readability and exclusion reason. This module does that translation once, per
platform, so the measure stays pure and the actor choice stays operational.

No actor id is hardcoded: the operator selects the actor and its input. The
normalizer accepts common aliases and documents the minimum contract below.

Minimum row contract:
  * a public URL (or enough identifiers to build one);
  * a publication date;
  * a view count, or a concurrent-viewer count on Twitch.

A row without URL or date is skipped and counted. A row with a URL and a date
but no readable value becomes an unreadable item, never a zero.
"""
import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from integrations import apify
from processing.engagement import EngagementItem, platform_key

URL_KEYS = (
    "item_url",
    "url",
    "post_url",
    "postUrl",
    "video_url",
    "videoUrl",
    "stream_url",
    "streamUrl",
    "web_url",
    "webUrl",
    "permalink",
)
DATE_KEYS = (
    "published_at",
    "publishedAt",
    "date",
    "created_at",
    "createdAt",
    "posted_at",
    "postedAt",
    "timestamp",
    "started_at",
    "startedAt",
)
ID_KEYS = (
    "item_id",
    "itemId",
    "id",
    "post_id",
    "postId",
    "video_id",
    "videoId",
    "stream_id",
    "streamId",
)
TYPE_KEYS = ("item_kind", "itemKind", "kind", "type", "content_type", "contentType")

VIEW_KEYS = (
    "views",
    "view_count",
    "viewCount",
    "views_count",
    "viewsCount",
    "play_count",
    "playCount",
    "stats.views",
    "statistics.viewCount",
    "statistics.playCount",
)
# Twitch is measured on live concurrency. Replay views are deliberately absent:
# a row with only ``views`` must become unreadable, never a VOD-based ratio.
TWITCH_VIEWER_KEYS = (
    "average_viewers",
    "averageViewers",
    "avg_viewers",
    "avgViewers",
    "average_concurrent_viewers",
    "averageConcurrentViewers",
    "concurrent_viewers",
    "concurrentViewers",
    "viewer_count",
    "viewerCount",
    "viewers",
)

READABLE_KEYS = ("readable", "is_readable", "isReadable")
UNREADABLE_KEYS = ("unreadable", "is_unreadable", "isUnreadable", "hidden")
HIDDEN_VIEW_KEYS = (
    "views_hidden",
    "viewsHidden",
    "hide_views",
    "hideViews",
    "views_are_hidden",
    "viewsAreHidden",
    "view_count_hidden",
    "viewCountHidden",
    "hidden_view_count",
    "hiddenViewCount",
    "views_private",
    "viewsPrivate",
)
PINNED_KEYS = ("pinned", "is_pinned", "isPinned", "pin")
AD_KEYS = (
    "is_ad",
    "isAd",
    "ad",
    "sponsored",
    "is_sponsored",
    "isSponsored",
    "paid",
    "is_paid",
    "isPaid",
)
LIVE_KEYS = ("is_live", "isLive", "live", "is_stream", "isStream", "stream")
CLIP_KEYS = ("is_clip", "isClip", "clip")
SHORT_KEYS = ("is_short", "isShort", "short", "is_shorts", "isShorts", "shorts")


@dataclass(frozen=True)
class EngagementCollection:
    """One snapshot of items collected for one platform account."""

    platform: str
    read_at: str
    items: tuple[EngagementItem, ...]
    raw_count: int
    skipped: int
    run_id: str | None = None
    dataset_id: str | None = None


def normalize_items(
    platform: str, rows: Iterable[dict], *, read_at: str
) -> EngagementCollection:
    """Normalize actor rows into one snapshot of engagement items.

    ``read_at`` is stamped on every item, so the measure can enforce M-03. It
    must be a valid ISO datetime; a row cannot carry its own reading time.
    """
    key = platform_key(platform)
    normalizer = _NORMALIZERS.get(key)
    if normalizer is None:
        raise ValueError(f"unsupported engagement platform: {platform!r}")

    stamp = _iso(read_at)
    if stamp is None:
        raise ValueError("read_at must be an ISO datetime")

    raw = list(rows)
    items = []
    skipped = 0
    for row in raw:
        if not isinstance(row, dict):
            skipped += 1
            continue
        item = normalizer(row, stamp)
        if item is None:
            skipped += 1
        else:
            items.append(item)

    return EngagementCollection(
        platform=key,
        read_at=stamp,
        items=tuple(items),
        raw_count=len(raw),
        skipped=skipped,
    )


def collect_with_apify(
    platform: str,
    actor_id: str,
    actor_input: dict,
    *,
    read_at: str | None = None,
    max_items: int | None = None,
    wait_seconds: int = apify.DEFAULT_WAIT_SECONDS,
) -> EngagementCollection:
    """Run one Actor and normalize its dataset rows into a snapshot.

    The caller owns the actor choice and its input; this function owns the
    translation. A failed run raises ``apify.ApifyError`` and produces no
    partial collection.
    """
    run = apify.run_actor_result(
        actor_id,
        actor_input,
        max_items=max_items,
        wait_seconds=wait_seconds,
    )
    stamp = _iso(read_at) if read_at else None
    stamp = stamp or datetime.now(UTC).isoformat(timespec="seconds")
    collection = normalize_items(platform, run.items, read_at=stamp)
    return replace(collection, run_id=run.run_id, dataset_id=run.dataset_id)


def _telegram(row: dict, read_at: str) -> EngagementItem | None:
    return _build(row, read_at=read_at, platform="telegram", kind="POST")


def _vk_video(row: dict, read_at: str) -> EngagementItem | None:
    return _build(
        row,
        read_at=read_at,
        platform="vk_video",
        kind=_vk_kind(row),
    )


def _rutube(row: dict, read_at: str) -> EngagementItem | None:
    return _build(
        row,
        read_at=read_at,
        platform="rutube",
        kind=_rutube_kind(row),
    )


def _youtube(row: dict, read_at: str) -> EngagementItem | None:
    return _build(
        row,
        read_at=read_at,
        platform="youtube",
        kind=_youtube_kind(row),
    )


def _twitch(row: dict, read_at: str) -> EngagementItem | None:
    kind = _twitch_kind(row)
    value_keys = TWITCH_VIEWER_KEYS if kind == "STREAM" else VIEW_KEYS
    return _build(
        row,
        read_at=read_at,
        platform="twitch",
        kind=kind,
        value_keys=value_keys,
    )


def _build(
    row: dict,
    *,
    read_at: str,
    platform: str,
    kind: str,
    value_keys: tuple[str, ...] = VIEW_KEYS,
) -> EngagementItem | None:
    url = _item_url(row, platform, kind)
    published = _iso(_first(row, DATE_KEYS))
    if not url or published is None:
        return None

    value = _int(_first(row, value_keys))
    hidden = _truthy(_first(row, HIDDEN_VIEW_KEYS))
    readable = (
        _truthy(_first(row, READABLE_KEYS, default=True))
        and not _truthy(_first(row, UNREADABLE_KEYS))
        and not hidden
        and value is not None
    )
    reason = _exclusion_reason(row, platform, kind)
    if not readable:
        value = None
        if reason is None:
            reason = "UNREADABLE"

    return EngagementItem(
        platform=platform,
        item_url=url,
        item_kind=kind,
        published_at=published,
        value=value,
        read_at=read_at,
        readable=readable,
        exclusion_reason=reason,
        item_id=_text(_first(row, ID_KEYS)),
    )


def _vk_kind(row: dict) -> str:
    text = _type_text(row)
    url = _text(_first(row, URL_KEYS)) or ""
    if _truthy(_first(row, CLIP_KEYS)) or "clip" in text or "/clip" in url:
        return "CLIP"
    if _truthy(_first(row, SHORT_KEYS)) or "short" in text or "/shorts" in url:
        return "SHORT"
    if _truthy(_first(row, LIVE_KEYS)) or text in ("live", "stream") or "/live" in url:
        return "STREAM"
    if text in ("post", "wall_post", "community_post"):
        return "POST"
    return "LONG_VIDEO"


def _rutube_kind(row: dict) -> str:
    text = _type_text(row)
    url = _text(_first(row, URL_KEYS)) or ""
    if _truthy(_first(row, CLIP_KEYS)) or "clip" in text or "/clip" in url:
        return "CLIP"
    if _truthy(_first(row, SHORT_KEYS)) or "short" in text or "/shorts" in url:
        return "SHORT"
    if _truthy(_first(row, LIVE_KEYS)) or text in ("live", "stream") or "/live" in url:
        return "STREAM"
    if text in ("post", "community_post"):
        return "POST"
    return "LONG_VIDEO"


def _youtube_kind(row: dict) -> str:
    text = _type_text(row)
    url = _text(_first(row, URL_KEYS)) or ""
    if _truthy(_first(row, SHORT_KEYS)) or "short" in text or "/shorts/" in url:
        return "SHORT"
    if _truthy(_first(row, CLIP_KEYS)) or text == "clip" or "/clip/" in url:
        return "CLIP"
    if text in ("post", "community_post"):
        return "POST"
    if text in ("live", "stream") or "/live" in url:
        return "STREAM"
    return "LONG_VIDEO"


def _twitch_kind(row: dict) -> str:
    text = _type_text(row)
    url = _text(_first(row, URL_KEYS)) or ""
    if text in ("vod", "replay", "archive", "highlight") or "/videos/" in url:
        return "VOD"
    if text == "clip" or "/clip" in url:
        return "CLIP"
    return "STREAM"


def _exclusion_reason(row: dict, platform: str, kind: str) -> str | None:
    if _truthy(_first(row, PINNED_KEYS)):
        return "PINNED"
    if _truthy(_first(row, AD_KEYS)):
        return "PAID_AD"
    if kind == "CLIP" or _truthy(_first(row, CLIP_KEYS)):
        return "CLIP"
    if _truthy(_first(row, LIVE_KEYS)) and not (
        platform == "twitch" and kind == "STREAM"
    ):
        return "LIVE"
    return None


def _item_url(row: dict, platform: str, kind: str) -> str | None:
    url = _text(_first(row, URL_KEYS))
    if url:
        return url

    item_id = _text(_first(row, ID_KEYS))
    if platform == "telegram":
        channel = _text(_first(row, ("channel_username", "channel", "username")))
        if channel and item_id:
            return f"https://t.me/{channel.lstrip('@')}/{item_id}"
    if platform == "vk_video":
        owner = _text(_first(row, ("owner_id", "ownerId")))
        if owner and item_id:
            prefix = "clip" if kind == "CLIP" else "video"
            return f"https://vk.com/{prefix}{owner}_{item_id}"
    if platform == "rutube" and item_id:
        return f"https://rutube.ru/video/{item_id}/"
    if platform == "youtube" and item_id:
        if kind == "SHORT":
            return f"https://www.youtube.com/shorts/{item_id}"
        return f"https://www.youtube.com/watch?v={item_id}"
    if platform == "twitch":
        channel = _text(
            _first(
                row,
                ("channel", "channel_login", "channelLogin", "user_login", "broadcaster_login"),
            )
        )
        if kind == "STREAM" and channel:
            return f"https://www.twitch.tv/{channel.lstrip('@')}"
        if kind == "VOD" and item_id:
            return f"https://www.twitch.tv/videos/{item_id}"
        if kind == "CLIP" and item_id:
            return f"https://clips.twitch.tv/{item_id}"
    return None


def _type_text(row: dict) -> str:
    value = _first(row, TYPE_KEYS)
    text = str(value or "").strip().lower().replace("-", "_")
    return " ".join(text.split())


def _first(row: dict, keys: tuple[str, ...], default=None):
    for key in keys:
        value = _lookup(row, key)
        if value not in (None, ""):
            return value
    return default


def _lookup(row: dict, path: str):
    current = row
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _truthy(value, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "да"}


def _int(value) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None

    text = str(value).strip().replace("\u00a0", "").replace(" ", "")
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d{1,3}(,\d{3})+", text) or re.fullmatch(
        r"-?\d{1,3}(\.\d{3})+", text
    ):
        return int(text.replace(",", "").replace(".", ""))
    return None


def _iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        seconds = float(value)
        if seconds > 10**12:
            seconds /= 1000
        try:
            parsed = datetime.fromtimestamp(seconds, UTC)
        except (OverflowError, OSError, ValueError):
            return None
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            try:
                return _iso(float(text))
            except ValueError:
                return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def _text(value) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


_NORMALIZERS = {
    "telegram": _telegram,
    "vk_video": _vk_video,
    "rutube": _rutube,
    "youtube": _youtube,
    "twitch": _twitch,
}
