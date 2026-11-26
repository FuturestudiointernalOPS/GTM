"""After scoring, read the contact pages of the best records that have none.

The scoring step already keeps the contacts written on the record's own page.
This step goes one page further, only where it is worth it:

- only records with no contact at all, and with a score;
- best scores first, at most ``limit`` records per run (each read costs time,
  and Russian sites often answer slowly);
- at most three pages per record, read with a short timeout;
- the first page that gives a contact stops the search for that record.

No model call: contacts are read by pattern (``processing.contact_finder``),
so each value is on the page it cites. A human still checks the row.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace

from integrations import webreader
from processing.contact_finder import contact_page_urls, find_in_text
from workflows.record_loop import LoopResult

log = logging.getLogger(__name__)

DEFAULT_LIMIT = 20
READ_TIMEOUT_SECONDS = 10

ReadPage = Callable[[str], webreader.PageRead]


def read_contact_page(url: str) -> webreader.PageRead:
    """The production reader: one page, short timeout, never raises."""
    return webreader.read_url(url, timeout_seconds=READ_TIMEOUT_SECONDS)


def enrich_contacts(
    scores: LoopResult,
    *,
    read: ReadPage = read_contact_page,
    limit: int = DEFAULT_LIMIT,
) -> LoopResult:
    """Return the same result, with contacts added where a contact page had one."""
    if limit <= 0:
        return scores

    targets = sorted(
        (
            index
            for index, record in enumerate(scores.scored)
            if not record.contacts and record.result.score is not None
        ),
        key=lambda index: -(scores.scored[index].result.score or 0),
    )[:limit]

    updated = list(scores.scored)
    found = 0
    for index in targets:
        record = updated[index]
        contacts = _search(record, read)
        if contacts:
            updated[index] = replace(record, contacts=contacts)
            found += 1

    log.info(
        "Contact pages: %s record(s) searched, %s with a new contact",
        len(targets),
        found,
    )
    return replace(scores, scored=tuple(updated))


def _search(record, read: ReadPage):
    source = record.source_url or ""
    for url in contact_page_urls(source, record.page_links, kind=record.kind):
        page = read(url)
        if page.error or not (page.text or page.links):
            continue
        contacts = find_in_text(
            page.text,
            page.links,
            source_url=source,
            found_on=url,
        )
        if contacts:
            return contacts
    return ()
