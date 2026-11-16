"""One record, from claims to score rows.

This is the chain the pipeline calls: extract the proven claims, enrich them into
measures, measure the engagement when a sample is available, score, and hand back
the rows the database expects. No business rule lives here; every rule is in
``processing/``.

Writing the rows is not done here: there is no database connection in this
process yet, so the caller receives the rows and decides where they go.
"""
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from processing import enrichment, extraction, scoring
from processing.engagement import EngagementItem, EngagementProfile, measure_engagement
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

    def run_row(self) -> dict | None:
        return self.result.to_score_run()

    def line_rows(self) -> list[dict]:
        return self.result.to_score_lines()


def score_creator_record(
    claims: Mapping[str, object],
    ledger: EvidenceLedger,
    *,
    items: Iterable[EngagementItem] | None = None,
    snapshot: str | None = None,
    measure_run_id: str | None = None,
) -> RecordScore:
    """Score one creator: claims, then sample, then points."""
    pulled = extraction.extract(
        claims, ledger, allowed=enrichment.CREATOR_FACT_KEYS
    )
    enriched = enrichment.creator_measures(pulled.facts)
    measures = enriched.measures

    sample = list(items or ())
    if sample:
        profile = EngagementProfile(
            main_platform=measures.platform or "",
            followers=measures.followers if measures.followers is not None else 0,
            followers_read_at=snapshot or sample[0].read_at,
        )
        measures = scoring.apply_engagement_measure(
            measures,
            measure_engagement(sample, profile),
            measure_run_id=measure_run_id,
        )

    return RecordScore(
        kind=CREATOR,
        result=scoring.score_creator(measures),
        rejected=pulled.rejected,
        notes=enriched.notes,
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
        notes=enriched.notes,
    )
