"""Telegram channel and group discovery through one Apify Actor.

Why this Actor: it reads tgstat and telegramic, the two public Telegram
directories, and returns listings in one row shape (handle, t.me link,
category, members, growth, reach, language, country). That is the discovery
step for creators on Telegram; the profile itself is still verified later.

Cost: the Actor is paid per event at $1.60 per 1,000 records. ``max_items`` is
therefore always sent with every run and the estimated ceiling is reported with
the result. A run with ``max_items=100`` costs at most about $0.16.
"""
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from integrations import apify

log = logging.getLogger(__name__)

ACTOR_ID = "jungle_synthesizer/tgstat-telegramic-group-directory-scraper"

PRICE_PER_1000_RECORDS_USD = Decimal("1.60")

SOURCE_DIRECTORIES = ("tgstat", "telegramic")
GROUP_TYPES = ("channel", "group")
REGIONS = ("global", "ua", "by", "uz", "kz", "kg", "ir", "cn", "in", "et")
RANKINGS = (
    "members",
    "members_7d",
    "members_30d",
    "members_t",
    "members_y",
    "reach",
    "ci",
    "mau",
    "msgs",
)

# The Actor's own category vocabulary. A category unknown to one directory
# simply adds nothing for that directory, so validation is about typos, not
# about guaranteeing a result.
CATEGORIES = (
    "news",
    "crypto",
    "tech",
    "economics",
    "entertainment",
    "education",
    "games",
    "music",
    "sport",
    "travel",
    "politics",
    "art",
    "design",
    "books",
    "health",
    "language",
    "beauty",
    "shopping",
    "science",
    "programming",
    "anime",
    "self-development",
    "tv-series-movies",
    "fitness",
    "animals",
    "celebrities",
    "funny",
    "jobs-marketing",
    "photo-video",
    "social-fun",
    "do-it-yourself",
    "analytics",
    "blogs",
    "random-talk",
    "business",
    "marketing",
    "psychology",
    "law",
    "career",
    "courses",
    "medicine",
    "pics",
    "video",
    "food",
    "quotes",
    "handmade",
    "babies",
    "nature",
    "construction",
    "instagram",
    "telegram",
    "transport",
    "religion",
    "esoterics",
    "edutainment",
    "apps",
    "other",
)


@dataclass(frozen=True)
class TelegramDirectoryResult:
    """A finished directory crawl and the two shapes it produces."""

    raw_items: list[dict]
    candidates: list[dict]
    resume_cursor: str | None
    run_id: str
    collected_at: str
    estimated_max_cost_usd: Decimal


def estimate_max_cost_usd(max_items: int) -> Decimal:
    """Upper bound of the Actor bill for a run capped at ``max_items`` rows."""
    max_items = _positive_int(max_items, "max_items")
    return (PRICE_PER_1000_RECORDS_USD * max_items / Decimal(1000)).quantize(
        Decimal("0.0001")
    )


def build_input(
    *,
    sources: Sequence[str] | None = None,
    group_types: Sequence[str] | None = None,
    categories: Sequence[str] | None = None,
    regions: Sequence[str] | None = None,
    rankings: Sequence[str] | None = None,
    max_items: int | None = None,
    resume_cursor: str | None = None,
    contact: str | None = None,
    intended_usage: str | None = None,
    improvement_suggestions: str | None = None,
) -> dict:
    """Build the Actor input, omitting every empty filter.

    An omitted filter means "all" to the Actor. A filter with a typo is refused
    here so a paid run never starts with an empty or misspelled selection.
    """
    payload: dict = {}
    _put_list(payload, "sources", sources, SOURCE_DIRECTORIES)
    _put_list(payload, "groupTypes", group_types, GROUP_TYPES)
    _put_list(payload, "categories", categories, CATEGORIES)
    _put_list(payload, "regions", regions, REGIONS)
    _put_list(payload, "rankings", rankings, RANKINGS)

    if max_items is not None:
        payload["maxItems"] = _positive_int(max_items, "max_items")
    if resume_cursor and resume_cursor.strip():
        payload["resumeCursor"] = resume_cursor.strip()

    for key, value in (
        ("sp_contact", contact),
        ("sp_intended_usage", intended_usage),
        ("sp_improvement_suggestions", improvement_suggestions),
    ):
        if value and value.strip():
            payload[key] = value.strip()

    return payload


def scrape(
    *,
    sources: Sequence[str] | None = None,
    group_types: Sequence[str] | None = None,
    categories: Sequence[str] | None = None,
    regions: Sequence[str] | None = None,
    rankings: Sequence[str] | None = None,
    max_items: int = 15,
    resume_cursor: str | None = None,
    contact: str | None = None,
    intended_usage: str | None = None,
    improvement_suggestions: str | None = None,
    wait_seconds: int | None = None,
) -> TelegramDirectoryResult:
    """Run the paid directory Actor and return raw rows plus creator leads.

    The resumable crawl is supported: pass the previous result's
    ``resume_cursor`` to continue without paying again for rows already
    delivered. The cursor expires with the account's run-retention window.
    """
    max_items = _positive_int(max_items, "max_items")
    run_input = build_input(
        sources=sources,
        group_types=group_types,
        categories=categories,
        regions=regions,
        rankings=rankings,
        max_items=max_items,
        resume_cursor=resume_cursor,
        contact=contact,
        intended_usage=intended_usage,
        improvement_suggestions=improvement_suggestions,
    )
    estimated = estimate_max_cost_usd(max_items)
    wait = apify.DEFAULT_WAIT_SECONDS if wait_seconds is None else wait_seconds

    log.warning(
        "Starting paid Apify actor %s: up to %s rows, estimated max $%s",
        ACTOR_ID,
        max_items,
        estimated,
    )
    run = apify.run_actor_result(
        ACTOR_ID,
        run_input,
        max_items=max_items,
        wait_seconds=wait,
        read_output=True,
    )

    collected_at = datetime.now(UTC).isoformat(timespec="seconds")
    candidates = [normalize_row(item, collected_at=collected_at) for item in run.items]
    return TelegramDirectoryResult(
        raw_items=run.items,
        candidates=candidates,
        resume_cursor=resume_cursor_from(run.output),
        run_id=run.run_id,
        collected_at=collected_at,
        estimated_max_cost_usd=estimated,
    )


def normalize_row(row: dict, *, collected_at: str) -> dict:
    """Turn one Actor row into the creator fields the next stage expects.

    The directory-specific metrics stay together under ``directory_facts`` so
    they are not mistaken for verified profile data. A private tgstat listing
    has no handle and no t.me link: both stay ``None`` instead of being
    invented.
    """
    handle = _text(row.get("telegram_handle"))
    if handle:
        handle = handle.lstrip("@")
    url = _text(row.get("telegram_url"))
    if not url and handle:
        url = f"https://t.me/{handle}"

    source_url = _text(row.get("source_url"))
    listing_id = _text(row.get("listing_id"))
    return {
        "main_platform": "Telegram",
        "handle": handle,
        "platform_url": url,
        "platform_account_id": handle or listing_id,
        "display_name": _text(row.get("group_name")),
        "country": _text(row.get("country")),
        "content_language": _text(row.get("language")),
        "followers": row.get("member_count"),
        "followers_read_at": collected_at,
        "source_refs": [
            {
                "directory": _text(row.get("source_directory")),
                "url": source_url,
                "listing_id": listing_id,
                "consulted_at": collected_at,
            }
        ],
        "directory_facts": {
            "category": _text(row.get("category")),
            "is_channel": row.get("is_channel"),
            "description": _text(row.get("description")),
            "member_growth": row.get("member_growth"),
            "growth_period": _text(row.get("growth_period")),
            "average_post_reach": row.get("average_post_reach"),
            "citation_index": row.get("citation_index"),
            "monthly_active_users": row.get("monthly_active_users"),
            "messages_7d": row.get("messages_7d"),
            "rating": row.get("rating"),
        },
    }


def resume_cursor_from(output: object) -> str | None:
    """Read the cursor from the run's OUTPUT, which may be a dict or JSON text."""
    if isinstance(output, str):
        text = output.strip()
        if not text:
            return None
        if text.startswith("{"):
            try:
                output = json.loads(text)
            except ValueError:
                return text
        else:
            return text
    if isinstance(output, dict):
        for key in ("resumeCursor", "resume_cursor"):
            value = output.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for value in output.values():
            if isinstance(value, dict):
                cursor = resume_cursor_from(value)
                if cursor:
                    return cursor
    return None


def _put_list(
    payload: dict,
    key: str,
    values: Sequence[str] | None,
    allowed: Sequence[str],
) -> None:
    """Validate one list filter and add it only when it selects something."""
    if values is None:
        return
    if isinstance(values, str):
        values = (values,)
    selected: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise TypeError(f"{key} must contain strings")
        value = value.strip()
        if not value or value in selected:
            continue
        if value not in allowed:
            raise ValueError(f"Unknown {key} value: {value!r}")
        selected.append(value)
    if selected:
        payload[key] = selected


def _positive_int(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None
