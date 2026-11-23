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
                notes="; ".join(record.audit_notes()) or None,
            )
            postgres.write_decision(
                connection,
                record_id=record.record_id,
                result=record.result,
                actor=computed_by,
            )
            postgres.write_contacts(
                connection,
                record_id=record.record_id,
                contacts=record.contacts,
                source_url=record.source_url or "",
                read_at=record.read_at or "",
            )
        except Exception:
            connection.rollback()
            raise

        connection.commit()
        return run_id

    return store, save_measure, write


def eligibility_sink(connection, *, computed_by: str = "weekly-run"):
    """Build the callable ``run_and_score`` uses to store an eligibility verdict.

    The verdict gets its own transaction: the score is already committed, and a
    failed check must roll back the verdict alone. The commit before writing
    closes whatever the verification callable may have opened (it is allowed to
    read the database), so the eligibility write starts from a clean state.
    """

    def write(record: RecordScore, decision):
        connection.commit()
        try:
            event_id = postgres.write_eligibility(
                connection,
                record_id=record.record_id,
                decision=decision,
                actor=computed_by,
            )
        except Exception:
            connection.rollback()
            raise

        connection.commit()
        return event_id

    return write


def postgres_run(
    *,
    connection,
    provider,
    fetch,
    computed_by: str = "weekly-run",
    verify=None,
    **collection,
) -> WeeklyRun:
    """Run one week and persist it. ``collection`` goes to ``run_and_score``.

    ``verify`` is optional: without it the run stops after the score, because
    the regulatory checks are a separate procedure and no verdict is invented.
    With it, each written score is followed by its eligibility decision.
    """
    records, save_measure, write = record_sinks(connection, computed_by=computed_by)
    write_eligibility = (
        eligibility_sink(connection, computed_by=computed_by)
        if verify is not None
        else None
    )
    return run_and_score(
        provider=provider,
        fetch=fetch,
        records=records,
        save_measure=save_measure,
        write=write,
        verify=verify,
        write_eligibility=write_eligibility,
        **collection,
    )
