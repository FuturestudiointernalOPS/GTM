"""One candidate, one record: ask the model, anchor the evidence, score.

The collection pipeline already produced pages and a ledger of raw text. This
module turns one candidate into a score: it asks the extractor model about the
page the candidate carries, records each claim against that page, and runs the
record flow.

Evidence is partitioned per record. Two creators may both claim a gaming share,
and their facts must not collide in one ledger; each candidate therefore gets its
own ledger, built from its own claims and its own source.

The anchor proves the model was shown a page, not that it read the value. So
every claim must come with a verbatim excerpt, and the loop checks that the
excerpt really appears in the page: a claim without one is dropped.
"""
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from ai.provider import AIProvider
from processing.deduplication import normalize_url
from processing.engagement import EngagementItem, EngagementMeasure
from processing.evidence import OBSERVED, EvidenceLedger, Source
from workflows import query_pool
from workflows.record_flow import (
    BUYER,
    CREATOR,
    RecordScore,
    creator_measure,
    score_buyer_record,
    score_creator_record,
)

if TYPE_CHECKING:
    from workflows.records import RecordKeys

MAX_TEXT = 20_000

# What the loop may call to obtain one creator's engagement sample.
SampleFor = Callable[["Candidate"], Iterable[EngagementItem] | None]

# What the loop may call to find or create the record behind a candidate.
RecordFor = Callable[["Candidate"], "RecordKeys | None"]

# What the loop may call to store a measure before scoring. It receives the
# measure and the platform account id, and returns the stored measure id.
SaveMeasure = Callable[[EngagementMeasure, str | None], str | None]

# Shortest excerpt accepted, once whitespace and case are normalised. A shorter
# one ("25", "60") would match by accident on almost any page.
MIN_QUOTE = 8

# The plan's query ids, to tell a creator page from a buyer page. The id prefix is
# not enough: "cis." carries both creators and buyers, only the block says which.
_QUERY_CATALOG = {query.id: query for query in query_pool.all_queries()}


@dataclass(frozen=True)
class Candidate:
    """One page to turn into a scored record.

    ``tax_id`` and ``legal_name`` only concern a buyer. They come from the
    labelled advertisement, which is where a buyer is born (scope §6.6); a page
    without them still gets a score in memory, but no buyer record is created.
    """

    kind: str
    record_id: str
    source_url: str
    text: str
    read_at: str
    tax_id: str | None = None
    legal_name: str | None = None


@dataclass(frozen=True)
class Claims:
    """What the model asserted, and the excerpts it says support it."""

    values: dict
    quotes: dict


@dataclass(frozen=True)
class LoopResult:
    """What one batch produced, and which records could not be scored."""

    scored: tuple[RecordScore, ...] = ()
    failed: tuple[tuple[str, str], ...] = ()


def kind_for_query(query_used: str | None) -> str | None:
    """Which filon a page belongs to, from the query block that found it."""
    if not query_used:
        return None
    query = _QUERY_CATALOG.get(query_used)
    if query is None:
        return None
    block = query.block.lower()
    if "creator" in block:
        return CREATOR
    if "buyer" in block:
        return BUYER
    return None


def candidates_from_pages(pages, reads=(), *, read_at: str) -> list[Candidate]:
    """Turn collected pages into candidates, one per page with readable text.

    The record id is the normalised page address until records exist: it is a
    stable handle for the run, not a database identifier.
    """
    texts = {read.url: read.text for read in reads if getattr(read, "text", None)}
    candidates: list[Candidate] = []

    for page in pages:
        url = page.get("url")
        kind = kind_for_query(page.get("query_used"))
        if not url or kind is None:
            continue
        text = texts.get(url) or page.get("snippet") or ""
        if not text.strip():
            continue
        candidates.append(
            Candidate(
                kind=kind,
                record_id=normalize_url(url) or url,
                source_url=url,
                text=text,
                read_at=read_at,
                tax_id=_first(page, "tax_id", "inn", "ogrn"),
                legal_name=_first(page, "legal_name"),
            )
        )

    return candidates


def _first(page: Mapping, *keys: str) -> str | None:
    """The first non-empty value among ``keys``, as text."""
    for key in keys:
        value = page.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def score_pages(
    provider: AIProvider,
    pages,
    reads=(),
    *,
    read_at: str,
    items_by_record: Mapping[str, Iterable[EngagementItem]] | None = None,
    sample_for: SampleFor | None = None,
    record_for: RecordFor | None = None,
    save_measure: SaveMeasure | None = None,
) -> LoopResult:
    """Score the fresh pages of one run: one model call per candidate."""
    return score_candidates(
        provider,
        candidates_from_pages(pages, reads, read_at=read_at),
        items_by_record=items_by_record,
        sample_for=sample_for,
        record_for=record_for,
        save_measure=save_measure,
    )


def collect_claims(provider: AIProvider, candidate: Candidate) -> Claims:
    """Ask the model about one page and keep the claims it is allowed to make."""
    payload = {
        "source_url": candidate.source_url,
        "text": (candidate.text or "")[:MAX_TEXT],
    }
    if candidate.kind == CREATOR:
        model = provider.extract_creator(payload)
    elif candidate.kind == BUYER:
        model = provider.extract_buyer(payload)
    else:
        raise ValueError(f"unknown candidate kind: {candidate.kind}")
    return Claims(
        values=model.claims.model_dump(exclude_none=True),
        quotes=dict(model.quotes),
    )


def verify_quotes(claims: Claims, *, text: str) -> tuple[dict, tuple[str, ...]]:
    """Keep only the claims backed by an excerpt actually present in the page.

    Matching ignores case and runs of whitespace: those are formatting, not
    content. Everything else is literal.
    """
    page = _normalize((text or "")[:MAX_TEXT])
    kept: dict = {}
    rejected: list[str] = []

    for key, value in claims.values.items():
        quote = _normalize(claims.quotes.get(key, ""))
        if len(quote) < MIN_QUOTE:
            rejected.append(f"{key}: citation manquante ou trop courte")
            continue
        if quote not in page:
            rejected.append(f"{key}: citation introuvable dans la page")
            continue
        kept[key] = value

    return kept, tuple(rejected)


def _normalize(text: str) -> str:
    return " ".join(text.split()).casefold()


def record_claims(
    claims: Mapping[str, object], *, source_url: str, read_at: str
) -> EvidenceLedger:
    """Anchor every claim to the page it was read on.

    The ledger is per record: reusing one across candidates would make two
    creators' gaming shares contradict each other.
    """
    ledger = EvidenceLedger()
    source = Source(url=source_url, consulted_at=read_at)
    for key, value in claims.items():
        ledger.add(key, value, source, proof_level=OBSERVED)
    return ledger


def score_candidate(
    provider: AIProvider,
    candidate: Candidate,
    *,
    items: Iterable[EngagementItem] | None = None,
    sample_for: SampleFor | None = None,
    record_for: RecordFor | None = None,
    save_measure: SaveMeasure | None = None,
    measure_run_id: str | None = None,
) -> RecordScore:
    """Turn one candidate into a score, with its own evidence.

    ``record_for`` gives the record and account ids, ``save_measure`` stores the
    measure before it is bound to the score line, and ``measure_run_id`` is the
    explicit form for tests.
    """
    keys = record_for(candidate) if record_for is not None else None
    record_id = keys.record_id if keys is not None else candidate.record_id
    account_id = keys.account_id if keys is not None else None

    if items is None and sample_for is not None:
        items = sample_for(candidate)

    collected = collect_claims(provider, candidate)
    values, rejected = verify_quotes(collected, text=candidate.text)
    ledger = record_claims(
        values, source_url=candidate.source_url, read_at=candidate.read_at
    )

    measure = None
    if candidate.kind == CREATOR:
        if items is not None:
            measure = creator_measure(values, ledger, items=items)
        bound = measure_run_id
        if measure is not None and save_measure is not None:
            bound = save_measure(measure, account_id)
        record = score_creator_record(
            values,
            ledger,
            measure=measure,
            measure_run_id=bound,
        )
    else:
        record = score_buyer_record(values, ledger)

    return replace(
        record,
        rejected=tuple(rejected) + record.rejected,
        record_id=record_id,
        account_id=account_id,
        measure=measure,
    )


def score_candidates(
    provider: AIProvider,
    candidates: Iterable[Candidate],
    *,
    items_by_record: Mapping[str, Iterable[EngagementItem]] | None = None,
    sample_for: SampleFor | None = None,
    record_for: RecordFor | None = None,
    save_measure: SaveMeasure | None = None,
) -> LoopResult:
    """Score a batch; a record that fails is listed, the others continue."""
    scored: list[RecordScore] = []
    failed: list[tuple[str, str]] = []
    samples = items_by_record or {}

    for candidate in candidates:
        try:
            scored.append(
                score_candidate(
                    provider,
                    candidate,
                    items=samples.get(candidate.record_id),
                    sample_for=sample_for,
                    record_for=record_for,
                    save_measure=save_measure,
                )
            )
        except Exception as error:  # noqa: BLE001 - one bad record must not stop the batch
            failed.append((candidate.record_id, str(error)))

    return LoopResult(scored=tuple(scored), failed=tuple(failed))
