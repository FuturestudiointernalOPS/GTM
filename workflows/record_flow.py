"""One record, from claims to score rows.

This is the chain the pipeline calls: extract the proven claims, enrich them into
measures, measure the engagement when a sample is available, score, and hand back
the rows the database expects. No business rule lives here; every rule is in
``processing/``.

Writing the rows is ``integrations/postgres.py``. The order matters: the measure
is written first, its id is handed to the score, then the score is written.
"""
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from processing import enrichment, extraction, scoring
from processing.engagement import (
    EngagementItem,
    EngagementMeasure,
    EngagementProfile,
    measure_engagement,
)
from processing.evidence import EvidenceLedger

CREATOR = "CREATOR"
BUYER = "BUYER"


@dataclass(frozen=True)
class RecordScore:
    """What one record produces, ready to be written or reviewed."""

    kind: str
    result: scoring.ScoreResult
    rejected: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    measure: EngagementMeasure | None = None

    def run_row(self) -> dict | None:
        return self.result.to_score_run()

    def line_rows(self) -> list[dict]:
        return self.result.to_score_lines()


def creator_measure(
    claims: Mapping[str, object],
    ledger: EvidenceLedger,
    *,
    items: Iterable[EngagementItem],
    snapshot: str | None = None,
) -> EngagementMeasure | None:
    """Measure the engagement alone, so it can be written before the score."""
    _, enriched = _enriched_creator(claims, ledger)
    return _measure(enriched.measures, items, snapshot)


def score_creator_record(
    claims: Mapping[str, object],
    ledger: EvidenceLedger,
    *,
    items: Iterable[EngagementItem] | None = None,
    measure: EngagementMeasure | None = None,
    snapshot: str | None = None,
    measure_run_id: str | None = None,
) -> RecordScore:
    """Score one creator: claims, then sample, then points.

    Pass either ``items`` (the sample is measured here) or ``measure`` (it was
    already measured, and possibly written). Passing ``measure_run_id`` binds the
    score line to the stored measure.
    """
    pulled, enriched = _enriched_creator(claims, ledger)
    measures = enriched.measures

    if measure is None and items is not None:
        measure = _measure(measures, items, snapshot)
    if measure is not None:
        measures = scoring.apply_engagement_measure(
            measures, measure, measure_run_id=measure_run_id
        )

    return RecordScore(
        kind=CREATOR,
        result=scoring.score_creator(measures),
        rejected=pulled.rejected,
        notes=_notes(pulled.rejected, enriched.notes),
        measure=measure,
    )


def score_buyer_record(
    claims: Mapping[str, object],
    ledger: EvidenceLedger,
) -> RecordScore:
    """Score one buyer. The buyer filon has no engagement measure."""
    pulled = extraction.extract(claims, ledger, allowed=enrichment.BUYER_FACT_KEYS)
    enriched = enrichment.buyer_measures(pulled.facts)

    return RecordScore(
        kind=BUYER,
        result=scoring.score_buyer(enriched.measures),
        rejected=pulled.rejected,
        notes=_notes(pulled.rejected, enriched.notes),
    )


def _enriched_creator(claims, ledger):
    pulled = extraction.extract(claims, ledger, allowed=enrichment.CREATOR_FACT_KEYS)
    return pulled, enrichment.creator_measures(pulled.facts)


def _measure(measures, items, snapshot) -> EngagementMeasure | None:
    sample = list(items or ())
    if not sample:
        return None
    profile = EngagementProfile(
        main_platform=measures.platform or "",
        followers=measures.followers if measures.followers is not None else 0,
        followers_read_at=snapshot or sample[0].read_at,
    )
    return measure_engagement(sample, profile)


def _notes(rejected: tuple[str, ...], notes: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(rejected) + tuple(notes)
