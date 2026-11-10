"""Discovery and extraction steps shared by both hunts.

Why a separate module: a creator hunt and a buyer hunt differ in their queries
and domain filters, not in how they call Exa and Apify. Keeping the two calls
here means a retry, a deduplication rule or a field change is fixed once.
"""
import logging
from collections.abc import Sequence
from dataclasses import dataclass

from integrations import apify, exa

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SearchSpec:
    """One search request: text, attribution id and optional filters.

    ``query_id`` is what the tracker stores as ``query_used``. It is optional
    so a plain string query still works and falls back to its own text.
    """

    text: str
    query_id: str | None = None
    include_domains: tuple[str, ...] = ()
    exclude_domains: tuple[str, ...] = ()
    exclude_text: tuple[str, ...] = ()


def clean_queries(
    queries: Sequence[str] | None,
    defaults: Sequence[str],
    *,
    what: str = "query",
) -> tuple[str, ...]:
    """Strip, drop blanks and duplicates, then fall back to the defaults.

    Order is kept: the first query is the most specific one, and the operator
    reading the log expects the same order as the constant.
    """
    candidates = queries if queries is not None else defaults
    if isinstance(candidates, str):
        candidates = (candidates,)
    cleaned: list[str] = []
    for query in candidates:
        query = query.strip() if isinstance(query, str) else ""
        if query and query not in cleaned:
            cleaned.append(query)
    if not cleaned:
        raise ValueError(f"At least one {what} is required")
    return tuple(cleaned)


def discover(
    queries: Sequence[str],
    *,
    include_domains: Sequence[str] | None = None,
    exclude_domains: Sequence[str] | None = None,
    exclude_text: Sequence[str] | None = None,
    num_results: int = exa.DEFAULT_RESULTS,
    start_published_date: str | None = None,
    with_text: bool = False,
) -> list[dict]:
    """Run plain-text queries through Exa and return unique pages.

    A page found by two queries is kept once, with the first query that found
    it: the same profile or company must not become two rows. Use
    ``discover_specs`` when each query needs its own domains or exclusions.
    """
    specs = (
        SearchSpec(
            text=query,
            include_domains=tuple(include_domains or ()),
            exclude_domains=tuple(exclude_domains or ()),
            exclude_text=tuple(exclude_text or ()),
        )
        for query in queries
    )
    return discover_specs(
        specs,
        num_results=num_results,
        start_published_date=start_published_date,
        with_text=with_text,
    )


def discover_specs(
    specs: Sequence[SearchSpec],
    *,
    num_results: int = exa.DEFAULT_RESULTS,
    start_published_date: str | None = None,
    with_text: bool = False,
) -> list[dict]:
    """Run every spec through Exa and return unique pages, in spec order.

    Each page carries ``query`` (the natural-language text sent) and
    ``query_used`` (the stable id from the pool, or the text for ad-hoc
    queries). When two specs find the same URL, the first one keeps the
    attribution, because the second did not discover a new target.
    """
    seen: set[str] = set()
    pages: list[dict] = []
    for spec in specs:
        if not spec.text or not spec.text.strip():
            raise ValueError("Exa query must not be empty")
        rows = exa.search(
            spec.text,
            num_results=num_results,
            include_domains=spec.include_domains or None,
            exclude_domains=spec.exclude_domains or None,
            exclude_text=spec.exclude_text or None,
            start_published_date=start_published_date,
            with_text=with_text,
        )
        query_used = spec.query_id or spec.text
        for row in rows:
            url = (row.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            pages.append(
                {
                    **row,
                    "url": url,
                    "query": spec.text,
                    "query_used": query_used,
                }
            )
        log.info("Exa discovery: %s page(s) after %r", len(pages), spec.text)
    return pages


def extract(
    actor_id: str | None,
    actor_input: dict | None,
    *,
    max_items: int | None = None,
    wait_seconds: int | None = None,
) -> list[dict]:
    """Run the extraction Actor when one is configured, otherwise do nothing.

    No actor means the operator only asked for discovery. An actor without its
    input is a configuration error: guessing the input would start a billed run
    with the wrong parameters.
    """
    if not actor_id:
        return []
    if actor_input is None:
        raise ValueError("actor_input is required when actor_id is set")
    options = {"max_items": max_items}
    if wait_seconds is not None:
        options["wait_seconds"] = wait_seconds
    return apify.run_actor(actor_id, actor_input, **options)
