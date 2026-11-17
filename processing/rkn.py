"""Compare a Roskomnadzor registry search with one creator page.

The search itself is not here: ``docs/verification.md`` §2.2 says the form is
public and independent of any link the creator publishes, and §2.4 says the
platform list is data, not code. What this module does is the part that must be
deterministic: decide what a returned entry proves.

Rules applied (V-03, V-04, V-08):

* a ``FOUND`` is not a match — an entry with the same name and another URL is a
  ``MISMATCH``, never a match;
* a ``NOT_FOUND`` only counts when the query is recorded, so the query travels
  in the reasons;
* several ambiguous entries go to ``MANUAL_REVIEW``, and a service that does not
  answer is ``PENDING`` — never ``NOT_FOUND``, which would accuse a page of not
  being registered because a website was down.
"""

from dataclasses import dataclass

from processing.deduplication import normalize_url
from processing.eligibility import (
    MANUAL_REVIEW,
    MISMATCH,
    NOT_FOUND,
    PARTIAL,
    PENDING,
    RKN_REGISTRY,
    VERIFIED,
    Check,
)


@dataclass(frozen=True)
class RegistryEntry:
    """One registry row: the page addresses it lists, its name, its identifier.

    A row lists the creator's addresses, which are not the registry's own card
    link: keeping every address of the row avoids guessing which column holds
    the page. The identifier is the strongest discriminant when both sides have
    one (§2.5).
    """

    urls: tuple[str, ...] = ()
    name: str = ""
    account_id: str | None = None


@dataclass(frozen=True)
class RegistrySearch:
    """What one search returned, and the query that produced it (V-04).

    ``lookalike`` says the answer came from a host that is not the official
    service: that is a review, never an absence (V-09).
    """

    query: str
    entries: tuple[RegistryEntry, ...] = ()
    unavailable: bool = False
    lookalike: bool = False


def compare(
    page_url: str,
    search: RegistrySearch,
    *,
    account_id: str | None = None,
    display_name: str | None = None,
) -> Check:
    """Turn one search into the registry check of a creator page."""
    if search.lookalike:
        # An answer from a host that imitates the service proves nothing about
        # the page, and is worth a human look (V-09).
        return Check(RKN_REGISTRY, MANUAL_REVIEW, ("LOOKALIKE_DOMAIN",))
    if search.unavailable:
        return Check(RKN_REGISTRY, PENDING, ("SERVICE_UNAVAILABLE",))

    target = normalize_url(page_url)
    if target is None:
        return Check(RKN_REGISTRY, PENDING, ("PAGE_URL_UNUSABLE",))

    query = f"QUERY:{search.query}"
    if not search.entries:
        return Check(RKN_REGISTRY, NOT_FOUND, (query, "NO_ENTRY"))

    matching = [entry for entry in search.entries if _lists(entry, target)]
    if matching:
        # The identifier is the strongest discriminant when both sides have one.
        identifiers = {entry.account_id for entry in matching if entry.account_id}
        if account_id and identifiers and account_id not in identifiers:
            return Check(RKN_REGISTRY, MISMATCH, (query, "IDENTIFIER_MISMATCH"))
        if account_id and account_id in identifiers:
            return Check(RKN_REGISTRY, VERIFIED, (query, "URL_AND_IDENTIFIER_MATCH"))
        return Check(RKN_REGISTRY, PARTIAL, (query, "URL_MATCH_IDENTIFIER_UNAVAILABLE"))

    # A name is a cross-check, never a key (§2.7, V-08).
    if display_name and any(
        _name_key(entry.name) == _name_key(display_name)
        for entry in search.entries
        if entry.name
    ):
        return Check(RKN_REGISTRY, MISMATCH, (query, "NAME_MATCH_URL_DIFFERS"))

    if len(search.entries) > 1:
        return Check(RKN_REGISTRY, MANUAL_REVIEW, (query, "AMBIGUOUS_ENTRIES"))

    return Check(RKN_REGISTRY, MANUAL_REVIEW, (query, "NO_MATCHING_ENTRY"))


def _name_key(name: str) -> str:
    """A soft comparison key: case, spaces, punctuation and emoji removed."""
    return "".join(
        character for character in (name or "").casefold() if character.isalnum()
    )


def _lists(entry: RegistryEntry, target: str) -> bool:
    """True when the row lists the page among its addresses."""
    return any(normalize_url(url) == target for url in entry.urls)
