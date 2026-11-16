"""The weekly run: collect, score, and hand the rows to a writer.

This is the entry point a human or cron calls. It wires the collection pipeline
to the per-record loop and, when a writer is supplied, persists the scores.

Everything external is injected: the collector (so a test needs no network), the
model provider, the actor fetcher and the writer. Nothing here decides a rule;
the rules live in ``processing/`` and the contracts in ``docs/``.
"""
from collections.abc import Callable
from dataclasses import dataclass

from ai.provider import AIProvider
from workflows.engagement_step import Fetcher, creator_sampler
from workflows.pipeline import PipelineResult, run_week
from workflows.record_flow import RecordScore
from workflows.record_loop import LoopResult, score_pages

Writer = Callable[[RecordScore], str | None]


@dataclass(frozen=True)
class WeeklyRun:
    """What one run produced: scores, and where they went."""

    collected_at: str
    fresh_pages: int
    scores: LoopResult
    written: tuple[str, ...] = ()
    write_failed: tuple[tuple[str, str], ...] = ()


def run_and_score(
    *,
    provider: AIProvider,
    fetch: Fetcher,
    collect: Callable[[], PipelineResult] | None = None,
    write: Writer | None = None,
    week: int | None = None,
    store=None,
    include_betting: bool = False,
    num_results: int = 10,
    read_top: int = 3,
    with_text: bool = False,
) -> WeeklyRun:
    """Run one week end to end.

    ``collect`` replaces the real collection, which is how tests stay offline.
    ``write`` is optional: without it the run returns the rows and writes
    nothing, which is the state of this project until the database is live. A
    writer that returns None (a rejected record, which produces no score run)
    counts as nothing written, not as a failure.
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

    scores = score_pages(
        provider,
        result.fresh,
        result.reads,
        read_at=result.collected_at,
        sample_for=creator_sampler(fetch),
    )

    written: list[str] = []
    write_failed: list[tuple[str, str]] = []
    if write is not None:
        for record in scores.scored:
            try:
                run_id = write(record)
            except Exception as error:  # noqa: BLE001 - one failed write must not stop the run
                write_failed.append((record.record_id or "", str(error)))
                continue
            if run_id is not None:
                written.append(run_id)

    return WeeklyRun(
        collected_at=result.collected_at,
        fresh_pages=len(result.fresh),
        scores=scores,
        written=tuple(written),
        write_failed=tuple(write_failed),
    )
