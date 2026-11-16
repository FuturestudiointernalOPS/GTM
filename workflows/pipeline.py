"""Deterministic collection pipeline: plan, discover, deduplicate, read, ledger.

This is the production path. The model does not appear here: routing is decided
by each query's ``service`` field, and every page or fact is stored with its
source and date. An optional analysis step reads the ledger later; it never
feeds raw pages back into this loop.
"""
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from integrations import webreader
from processing.deduplication import JsonRecordStore, partition_new
from processing.evidence import UNVERIFIED, EvidenceLedger, Source
from workflows import buyer_hunt, creator_hunt, query_pool

log = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Everything one weekly run produced, for audit and for the next stage."""

    plan: tuple
    pages: list[dict]
    skipped: list[dict]
    reads: list
    ledger: EvidenceLedger
    collected_at: str


def run_week(
    week: int | None = None,
    *,
    include_betting: bool = False,
    store: JsonRecordStore | None = None,
    num_results: int = 10,
    read_top: int = 3,
    read_max_chars: int = webreader.DEFAULT_MAX_CHARS,
    read_batch_max: int = webreader.MAX_URLS_PER_BATCH,
    with_text: bool = False,
) -> PipelineResult:
    """Run one weekly plan end to end.

    Steps, in order: build the deterministic plan, discover pages through the
    service each query names, drop URLs or handles already in the store, read
    the top fresh pages per query, then record the evidence. The store is
    updated so a later run skips what this one already saw.

    The caller decides persistence by passing a ``JsonRecordStore`` with a
    path; without one the store is in-memory only.
    """
    if not 1 <= read_batch_max <= webreader.MAX_URLS_PER_BATCH:
        raise ValueError(
            f"read_batch_max must be between 1 and {webreader.MAX_URLS_PER_BATCH}"
        )
    if read_top < 0:
        raise ValueError("read_top must be zero or positive")

    store = store or JsonRecordStore()
    creator = query_pool.creator_plan(week)
    buyer = query_pool.buyer_plan(week, include_betting=include_betting)
    plan = creator + buyer

    pages = list(
        creator_hunt.hunt_plan(
            creator,
            num_results=num_results,
            with_text=with_text,
        )["pages"]
    )
    pages += buyer_hunt.hunt_plan(
        buyer,
        num_results=num_results,
        with_text=with_text,
    )["pages"]

    fresh, skipped = partition_new(pages, store)
    urls_to_read = _urls_to_read(fresh, read_top=read_top)

    reads: list = []
    for start in range(0, len(urls_to_read), read_batch_max):
        reads.extend(
            webreader.read_urls(
                urls_to_read[start : start + read_batch_max],
                max_chars=read_max_chars,
            )
        )

    collected_at = datetime.now(UTC).isoformat(timespec="seconds")
    ledger = _build_ledger(fresh, reads, collected_at=collected_at)

    store.add(urls=[page["url"] for page in fresh])
    log.info(
        "Pipeline run: %s page(s) found, %s skipped, %s read",
        len(fresh),
        len(skipped),
        len(reads),
    )
    return PipelineResult(
        plan=plan,
        pages=pages,
        skipped=skipped,
        reads=reads,
        ledger=ledger,
        collected_at=collected_at,
    )


def _urls_to_read(fresh: list[dict], *, read_top: int) -> list[str]:
    """Take up to ``read_top`` fresh URLs per query, in discovery order."""
    grouped: dict[str, list[str]] = {}
    for page in fresh:
        key = page.get("query_used") or page.get("query") or "unknown"
        grouped.setdefault(key, []).append(page["url"])

    urls: list[str] = []
    for group in grouped.values():
        urls.extend(group[:read_top])

    # Keep first-seen order and avoid reading the same URL twice.
    return list(dict.fromkeys(urls))


def _build_ledger(
    fresh: list[dict],
    reads: list,
    *,
    collected_at: str,
) -> EvidenceLedger:
    ledger = EvidenceLedger()
    for page in fresh:
        source = Source(
            url=page["url"],
            consulted_at=collected_at,
            query_used=page.get("query_used"),
            service=page.get("service"),
        )
        ledger.add("url", page["url"], source, confidence=UNVERIFIED)
        snippet = page.get("snippet") or page.get("text")
        if snippet:
            ledger.add("text", snippet, source, confidence=UNVERIFIED)
    for read in reads:
        if read.text:
            ledger.add(
                "text",
                read.text,
                Source(url=read.url, consulted_at=collected_at),
                confidence=UNVERIFIED,
            )
    return ledger
