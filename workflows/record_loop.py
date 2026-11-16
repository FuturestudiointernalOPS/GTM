"""One candidate, one record: ask the model, anchor the evidence, score.

The collection pipeline already produced pages and a ledger of raw text. This
module turns one candidate into a score: it asks the extractor model about the
page the candidate carries, records each claim against that page, and runs the
record flow.

Evidence is partitioned per record. Two creators may both claim a gaming share,
and their facts must not collide in one ledger; each candidate therefore gets its
own ledger, built from its own claims and its own source.

The anchor proves the model was shown a page, not that it read the value. Asking
for a verbatim quote per claim is the next hardening step, not a property of this
loop yet.
"""
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from ai.provider import AIProvider
from processing.engagement import EngagementItem
from processing.evidence import OBSERVED, EvidenceLedger, Source
from workflows.record_flow import (
    BUYER,
    CREATOR,
    RecordScore,
    score_buyer_record,
    score_creator_record,
)

MAX_TEXT = 20_000


@dataclass(frozen=True)
class Candidate:
    """One page to turn into a scored record."""

    kind: str
    record_id: str
    source_url: str
    text: str
    read_at: str


@dataclass(frozen=True)
class LoopResult:
    """What one batch produced, and which records could not be scored."""

    scored: tuple[RecordScore, ...] = ()
    failed: tuple[tuple[str, str], ...] = ()


def collect_claims(provider: AIProvider, candidate: Candidate) -> dict:
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
    return model.model_dump(exclude_none=True)


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
    measure_run_id: str | None = None,
) -> RecordScore:
    """Turn one candidate into a score, with its own evidence."""
    claims = collect_claims(provider, candidate)
    ledger = record_claims(
        claims, source_url=candidate.source_url, read_at=candidate.read_at
    )

    if candidate.kind == CREATOR:
        return score_creator_record(
            claims,
            ledger,
            items=items,
            measure_run_id=measure_run_id,
        )
    return score_buyer_record(claims, ledger)


def score_candidates(
    provider: AIProvider,
    candidates: Iterable[Candidate],
    *,
    items_by_record: Mapping[str, Iterable[EngagementItem]] | None = None,
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
                )
            )
        except Exception as error:  # noqa: BLE001 - one bad record must not stop the batch
            failed.append((candidate.record_id, str(error)))

    return LoopResult(scored=tuple(scored), failed=tuple(failed))
