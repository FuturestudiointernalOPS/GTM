"""The weekly run wired to PostgreSQL: fiches, measures, scores.

``run_and_score`` takes three injected callables. This module builds them from
one connection, so the production call is a single line:

    postgres_run(connection=connection, provider=provider, fetch=fetch)

Transaction boundaries, and why they are here:

* the run scores every candidate before writing anything, so the fiches and the
  engagement measures are created during one long transaction;
* each score therefore starts with a commit of that pending work, then writes in
  its own transaction. A failed write rolls back one score, not the whole run,
  and a failed statement cannot abort the writes that follow;
* a rejected record produces no score run, but it does produce a decision: the
  fiche moves to REJECTED through ``transition_record()``. Its fiche and its
  measure stay — a fiche is an identity, a measure is a fact, and neither is the
  decision. Forgetting a rejected creator is how the next run would collect and
  score it again.

The caller keeps the connection (and closes it); this module never connects.
"""
from integrations import postgres
from integrations.record_store import PostgresRecordStore
from workflows.record_flow import RecordScore
from workflows.weekly_run import WeeklyRun, run_and_score


def record_sinks(connection, *, computed_by: str = "weekly-run"):
    """Build the three callables ``run_and_score`` accepts, from one connection."""
    store = PostgresRecordStore(connection)

    def save_measure(measure, account_id):
        if account_id is None:
            # No platform account, no measure row: the score line stays unbound
            # rather than pointing at an account that does not exist.
            return None
        return postgres.write_measure(
            connection,
            account_id=account_id,
            measure=measure,
            computed_by=computed_by,
        )

    def write(record: RecordScore):
        # Persist the fiches and measures created while scoring, then give the
        # score and its decision their own transaction.
        connection.commit()
        try:
            run_id = postgres.write_score(
                connection,
                record_id=record.record_id,
                result=record.result,
                computed_by=computed_by,
                notes="; ".join(record.notes) or None,
            )
            postgres.write_decision(
                connection,
                record_id=record.record_id,
                result=record.result,
                actor=computed_by,
            )
        except Exception:
            connection.rollback()
            raise

        connection.commit()
        return run_id

    return store, save_measure, write


def postgres_run(
    *,
    connection,
    provider,
    fetch,
    computed_by: str = "weekly-run",
    **collection,
) -> WeeklyRun:
    """Run one week and persist it. ``collection`` goes to ``run_and_score``."""
    records, save_measure, write = record_sinks(
        connection, computed_by=computed_by
    )
    return run_and_score(
        provider=provider,
        fetch=fetch,
        records=records,
        save_measure=save_measure,
        write=write,
        **collection,
    )
