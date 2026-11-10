"""Buyer hunt: find companies that sell to Russian-speaking gamers.

Scope §6.1-6.2. The main signal is a labelled ad paid in the last 90 days;
this module does not read the label yet, so a discovered company is a lead, not
a qualified buyer. Betting brands are not in the default queries on purpose:
they need a licence check before a record is created (§6.4, E-B-04), so a human
adds that query explicitly once the check exists.
"""
import logging
from collections.abc import Sequence

from workflows.query_pool import Query
from workflows.search import clean_queries, discover, discover_specs, extract

log = logging.getLogger(__name__)

# Instagram and Facebook are out of scope for collection (scope §5.2).
EXCLUDED_DOMAINS = ("instagram.com", "facebook.com")

# Covers the families of scope §6.1 except betting. Russian and English are
# mixed because agency names and product pages use both.
DEFAULT_QUERIES = (
    "издатель игр Россия",
    "разработчик игр Россия",
    "игровая периферия магазин Россия",
    "киберспортивная команда Россия",
    "компьютерный клуб Россия",
    "gaming agency Russia influence",
    "реклама игра erid ИНН",
)


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
    """Discover company pages and, when configured, extract company rows.

    Returns ``{"queries", "pages", "profiles"}``:

    - ``pages`` are Exa rows (URL, title, date) with the ``query`` that found
      them;
    - ``profiles`` are the Actor dataset rows, unchanged, or an empty list when
      no Actor was given.

    There is no domain allow-list here: a buyer can live on its own domain. The
    excluded domains are the platforms we never collect from.
    """
    selected = clean_queries(queries, DEFAULT_QUERIES)
    pages = discover(
        selected,
        exclude_domains=EXCLUDED_DOMAINS,
        num_results=num_results,
        start_published_date=start_published_date,
        with_text=with_text,
    )
    profiles = extract(
        actor_id,
        actor_input,
        max_items=max_items,
        wait_seconds=wait_seconds,
    )
    return {"queries": list(selected), "pages": pages, "profiles": profiles}


def hunt_plan(
    plan: Sequence[Query],
    *,
    num_results: int = 10,
    with_text: bool = False,
    start_published_date: str | None = None,
    actor_id: str | None = None,
    actor_input: dict | None = None,
    max_items: int | None = None,
    wait_seconds: int | None = None,
) -> dict:
    """Run a planned list of buyer queries and return attributed pages.

    Each page keeps ``query`` (the Exa text) and ``query_used`` (the stable pool
    id). Use ``query_pool.buyer_plan`` to build the list; betting queries stay
    out unless the caller explicitly added them after a licence check.
    """
    specs = [query.as_search_spec() for query in plan]
    found = discover_specs(
        specs,
        num_results=num_results,
        start_published_date=start_published_date,
        with_text=with_text,
    )
    profiles = extract(
        actor_id,
        actor_input,
        max_items=max_items,
        wait_seconds=wait_seconds,
    )
    return {
        "queries": [query.id for query in plan],
        "pages": found,
        "profiles": profiles,
    }
