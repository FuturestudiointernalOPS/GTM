"""The weekly run: collect, score, and hand the rows to a writer.

This is the entry point a human or cron calls. It wires the collection pipeline
to the per-record loop and, when a writer is supplied, persists the scores.

Everything external is injected: the collector (so a test needs no network), the
model provider, the actor fetcher, the writer and the eligibility step. Nothing
here decides a rule; the rules live in ``processing/`` and the contracts in
``docs/``.
"""

from collections.abc import Callable
from dataclasses import dataclass

from ai.provider import AIProvider
from workflows.eligibility_step import (
    EligibilityWriter,
    VerifyFor,
    decide,
)
from workflows.engagement_step import Fetcher, creator_sampler
from workflows.pipeline import PipelineResult, run_week
from workflows.record_flow import RecordScore
from workflows.record_loop import LoopResult, SaveMeasure, score_pages
from workflows.records import RecordStore, ensure_record

Writer = Callable[[RecordScore], str | None]


@dataclass(frozen=True)
class WeeklyRun:
    """What one run produced: scores, and where they went."""

    collected_at: str
    fresh_pages: int
    scores: LoopResult
    written: tuple[str, ...] = ()
    write_failed: tuple[tuple[str, str], ...] = ()
    eligible: tuple[tuple[str, str], ...] = ()
    eligibility_skipped: tuple[str, ...] = ()
    eligibility_failed: tuple[tuple[str, str], ...] = ()


def run_and_score(
    *,
    provider: AIProvider,
    fetch: Fetcher,
    collect: Callable[[], PipelineResult] | None = None,
    write: Writer | None = None,
    records: RecordStore | None = None,
    save_measure: SaveMeasure | None = None,
    verify: VerifyFor | None = None,
    write_eligibility: EligibilityWriter | None = None,
    week: int | None = None,
    store=None,
    include_betting: bool = False,
    num_results: int = 10,
    read_top: int = 3,
    with_text: bool = False,
) -> WeeklyRun:
    """Run one week end to end.

    ``collect`` replaces the real collection, which is how tests stay offline.
    ``records`` finds or creates the record behind each candidate, so the rows
    carry real ids; ``save_measure`` stores the measure before the score line
    references it. ``write`` is optional: without it the run returns the rows and
    writes nothing. A writer that returns None (a rejected record, which produces
    no score run) counts as nothing written, not as a failure.

    ``verify`` and ``write_eligibility`` close the regulatory step after a score
    is written. Both must be provided: the first returns the check results for a
    record (or None when no procedure ran), the second stores the decision. A
    record without a verification is reported as skipped, never as eligible.
    """
    result = (
        collect()
        if collect is not None
        else run_week(
            week=week,
            include_betting=include_betting,
            store=store,
            num_results=num_results,
            read_top=read_top,
            with_text=with_text,
        )
    )

    record_for = None
    if records is not None:
        record_for = _record_finder(records)

    scores = score_pages(
        provider,
        result.fresh,
        result.reads,
        read_at=result.collected_at,
        sample_for=creator_sampler(fetch),
        record_for=record_for,
        save_measure=save_measure,
    )

    written: list[str] = []
    write_failed: list[tuple[str, str]] = []
    eligible: list[tuple[str, str]] = []
    eligibility_skipped: list[str] = []
    eligibility_failed: list[tuple[str, str]] = []
    if write is not None:
        for record in scores.scored:
            try:
                run_id = write(record)
            except Exception as error:  # noqa: BLE001 - one failed write must not stop the run
                write_failed.append((record.record_id or "", str(error)))
                continue
            if run_id is None:
                continue
            written.append(run_id)

            if verify is None or write_eligibility is None:
                continue
            record_key = record.record_id or ""
            try:
                verification = verify(record)
                if verification is None:
                    # No procedure ran for this record: no verdict, no default.
                    eligibility_skipped.append(record_key)
                    continue
                decision = decide(record.kind, verification)
                write_eligibility(record, decision)
                eligible.append(
                    (record_key, decision.status or decision.workflow_status)
                )
            except Exception as error:  # noqa: BLE001 - one bad check must not stop the run
                eligibility_failed.append((record_key, str(error)))

    return WeeklyRun(
        collected_at=result.collected_at,
        fresh_pages=len(result.fresh),
        scores=scores,
        written=tuple(written),
        write_failed=tuple(write_failed),
        eligible=tuple(eligible),
        eligibility_skipped=tuple(eligibility_skipped),
        eligibility_failed=tuple(eligibility_failed),
    )


def _record_finder(records: RecordStore):
    """The hook ``score_pages`` expects, bound to one store."""

    def find(candidate):
        return ensure_record(
            records,
            candidate,
            tax_id=candidate.tax_id,
            legal_name=candidate.legal_name,
        )

    return find
