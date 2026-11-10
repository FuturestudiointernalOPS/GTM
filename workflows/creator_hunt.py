"""Creator hunt: find Russian gaming creators, then read their profiles.

Scope §5.1-5.2: content and audience in Russian, gaming or esport, 5,000 to
300,000 followers. This module only collects. Followers, activity and the RKN
link are facts that processing/ and compliance/ must verify; no score is
computed here, because a search result is not a proof and a score must never
absorb eligibility (H-04).
"""
import logging
from collections.abc import Sequence
from urllib.parse import urlsplit

from workflows.search import clean_queries, discover, extract

log = logging.getLogger(__name__)

# Allowed by scope §5.2. Instagram and Facebook are excluded from collection,
# so they are also excluded from the search itself.
ALLOWED_DOMAINS = (
    "vk.com",
    "vkvideo.ru",
    "twitch.tv",
    "rutube.ru",
    "t.me",
    "youtube.com",
    "youtu.be",
)
EXCLUDED_DOMAINS = ("instagram.com", "facebook.com")

# Russian and English queries: creators describe themselves in both. They are
# starting points for the operator, not a fixed list from the scope.
DEFAULT_QUERIES = (
    "стример киберспорт Россия",
    "игровой стример ВКонтакте",
    "gaming streamer Russia Twitch",
    "киберспортивная команда игроки",
)


def platform_for(url: str) -> str | None:
    """Return the scope platform for a URL, or None when it is out of scope."""
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    if host == "youtu.be" or _on(host, "youtube.com"):
        return "YouTube"
    if _on(host, "t.me") or _on(host, "telegram.me"):
        return "Telegram"
    if _on(host, "vk.com") or _on(host, "vkvideo.ru"):
        return "VK Video"
    if _on(host, "twitch.tv"):
        return "Twitch"
    if _on(host, "rutube.ru"):
        return "Rutube"
    return None


def hunt(
    queries: Sequence[str] | None = None,
    *,
    num_results: int = 10,
    with_text: bool = False,
    start_published_date: str | None = None,
    actor_id: str | None = None,
    actor_input: dict | None = None,
    max_items: int | None = None,
    wait_seconds: int | None = None,
) -> dict:
    """Discover creator pages and, when configured, extract profile rows.

    Returns ``{"queries", "pages", "profiles"}``:

    - ``pages`` are Exa rows (URL, title, date) with the ``query`` that found
      them and the scope ``platform``;
    - ``profiles`` are the Actor dataset rows, unchanged, or an empty list when
      no Actor was given.

    Out-of-scope pages are dropped with a warning rather than silently kept.
    """
    selected = clean_queries(queries, DEFAULT_QUERIES)
    found = discover(
        selected,
        include_domains=ALLOWED_DOMAINS,
        exclude_domains=EXCLUDED_DOMAINS,
        num_results=num_results,
        start_published_date=start_published_date,
        with_text=with_text,
    )

    pages: list[dict] = []
    for page in found:
        platform = platform_for(page["url"])
        if platform is None:
            log.warning("Creator search returned an out-of-scope page: %s", page["url"])
            continue
        pages.append({**page, "platform": platform})

    profiles = extract(
        actor_id,
        actor_input,
        max_items=max_items,
        wait_seconds=wait_seconds,
    )
    return {"queries": list(selected), "pages": pages, "profiles": profiles}


def _on(host: str, domain: str) -> bool:
    """True for the domain itself and its subdomains, never for look-alikes."""
    return host == domain or host.endswith(f".{domain}")
