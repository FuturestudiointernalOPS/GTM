"""Write an engagement measure and a score into PostgreSQL.

No driver is imported here: the caller passes a connection (psycopg), so this
module is tested against a fake and the deployment chooses the driver.

The order matters. The measure is written first, its id is bound to the score
line, then the score is written. The caller owns the transaction: one commit for
the measure and the score, or nothing.

A record rejected by an elimination, or outside the profile, writes nothing: that
is a decision, not a score of zero. A measure from a platform outside the policy
writes nothing either, because no measure run exists for it.
"""

import json
from decimal import Decimal
from fractions import Fraction

from config import settings
from integrations import sync_store
from processing import eligibility
from processing.engagement import MEASURED, EngagementMeasure
from processing.scoring import (
    CRITERIA_VERSION,
    OUT_OF_PROFILE,
    PRESELECTED,
    QUALIFIED,
    REJECTED,
    THRESHOLD,
    TO_REVIEW,
    ScoreResult,
)


class PostgresNotConfigured(RuntimeError):
    """The connection cannot be opened: no driver, or no address."""


def is_configured() -> bool:
    """True when an address is set. The driver is only needed to connect."""
    return bool(settings.DATABASE_URL)


def connect(dsn: str | None = None, *, driver=None):
    """Open a connection, importing the driver here and nowhere else.

    The driver is a parameter so tests need no PostgreSQL client, and so the
    deployment can pin whichever one it installs. Everything else in this module
    only needs an object exposing ``cursor()``.
    """
    if driver is None:
        try:
            import psycopg as driver
        except ImportError as error:
            raise PostgresNotConfigured(
                "psycopg is not installed: add psycopg[binary] to the environment"
            ) from error

    target = dsn or settings.DATABASE_URL
    if not target:
        raise PostgresNotConfigured("DATABASE_URL is not set: add it to the .env file")
    return driver.connect(target)


INSERT_MEASURE = """
INSERT INTO engagement_measure_run (
    creator_platform_account_id, criteria_version, status, measure_kind,
    statistic, value, sample_size, unreadable_count, window_start, window_end,
    window_mode, read_at, sample_hash, flags, computed_by
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
RETURNING id
"""

INSERT_RUN = """
INSERT INTO score_run (
    record_id, criteria_version, score, total_exact, incomplete,
    bounds_lower, bounds_upper, proposal, facts_hash, computed_by, notes
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
RETURNING id
"""

INSERT_LINE = """
INSERT INTO score_line (
    score_run_id, criterion_code, measure, status, points_exact,
    points_max, blocking, engagement_measure_run_id, reason
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

SELECT_DECISION = "SELECT workflow_status, score_proposal FROM record WHERE id = %s"

# The schema's single entry point for a status change: it writes the journal
# entry, then the status. Calling it directly is not allowed (§5.5 of
# docs/data-model.md).
SELECT_TRANSITION = """
SELECT transition_record(
    %s::uuid, %s::workflow_status, %s, %s, %s::decision_type, %s, NULL, %s::jsonb
)
"""

# Score columns only: workflow_status belongs to transition_record().
UPDATE_DECISION = """
UPDATE record
SET score = %s,
    score_total_exact = %s,
    score_incomplete = %s,
    score_proposal = %s,
    criteria_version = %s,
    updated_at = now()
WHERE id = %s
"""

# A score stops at SCORED. PRESELECTED and QUALIFIED come after the regulatory
# check, and H-04 says a score never replaces one, so writing them here would
# skip a step the journey requires.
_DECISION_STATUS = {
    PRESELECTED: "SCORED",
    QUALIFIED: "SCORED",
    TO_REVIEW: "TO_REVIEW",
    REJECTED: "REJECTED",
    OUT_OF_PROFILE: "REJECTED",
}

# score_proposal only accepts four values: "outside the profile" is stored as a
# rejection, and the exact proposal survives in the journal entry's payload.
_STORABLE_PROPOSAL = {OUT_OF_PROFILE: REJECTED}


def write_measure(
    connection,
    *,
    account_id,
    measure: EngagementMeasure,
    computed_by: str,
    criteria_version: str = CRITERIA_VERSION,
) -> str | None:
    """Store one measure run and return its id, or None when there is no row."""
    if measure.measure_kind is None:
        return None
    if measure.status == MEASURED and measure.value is None:
        raise ValueError("a measured engagement must carry a value")

    params = (
        str(account_id),
        criteria_version,
        measure.status,
        measure.measure_kind,
        measure.statistic,
        _numeric(measure.value),
        measure.sample_size,
        measure.unreadable_count,
        measure.window_start,
        measure.window_end,
        measure.window_mode,
        measure.read_at,
        measure.sample_hash,
        list(measure.flags),
        computed_by,
    )

    with connection.cursor() as cursor:
        cursor.execute(INSERT_MEASURE, params)
        return str(cursor.fetchone()[0])


def write_score(
    connection,
    *,
    record_id,
    result: ScoreResult,
    computed_by: str,
    facts_hash: str | None = None,
    notes: str | None = None,
) -> str | None:
    """Store one score run and its lines, and return the run id."""
    run = result.to_score_run()
    if run is None:
        return None
    if record_id is None:
        raise ValueError("a score needs a record id: no record was found or created")

    lines = result.to_score_lines()
    with connection.cursor() as cursor:
        cursor.execute(
            INSERT_RUN,
            (
                str(record_id),
                run["criteria_version"],
                run["score"],
                run["total_exact"],
                run["incomplete"],
                run["bounds_lower"],
                run["bounds_upper"],
                run["proposal"],
                facts_hash,
                computed_by,
                notes,
            ),
        )
        run_id = cursor.fetchone()[0]
        for line in lines:
            cursor.execute(
                INSERT_LINE,
                (
                    run_id,
                    line["criterion_code"],
                    line["measure"],
                    line["status"],
                    line["points_exact"],
                    line["points_max"],
                    line["blocking"],
                    line["engagement_measure_run_id"],
                    line["reason"],
                ),
            )
    return str(run_id)


def write_contacts(
    connection,
    *,
    record_id,
    contacts,
    source_url: str,
    read_at: str,
) -> tuple[str, ...]:
    """Store the public contacts discovered on the record's page.

    A contact already present is never overwritten or reactivated: a human may
    have verified it or recorded an opt-out. The discovery path only adds what
    is missing. ``source_date`` is the read date, as the retention rule asks.
    """
    if record_id is None or not contacts:
        return ()

    source_date = (read_at or "")[:10]
    if len(source_date) != 10:
        raise ValueError("a contact needs the date its page was read")

    stored: list[str] = []
    for contact in contacts:
        notes = " | ".join(
            part for part in (contact.description, f"citation: {contact.quote}") if part
        )
        stored.append(
            sync_store.insert_discovered_contact(
                connection,
                record_id=str(record_id),
                role=contact.role,
                person_name=contact.person_name,
                channel_type=contact.channel_type,
                channel_value=contact.channel_value,
                source_url=source_url or "",
                source_date=source_date,
                notes=notes or None,
            )
        )
    return tuple(stored)


def write_decision(
    connection,
    *,
    record_id,
    result: ScoreResult,
    actor: str,
) -> str:
    """Sync the fiche with the score's decision, and return the status written.

    Two things happen, in this order: a status change goes through
    ``transition_record()`` (journal first, then status), and the score columns
    are updated. The score columns are not part of the status: a rescore rewrites
    them without pretending the fiche moved.

    A status change is only attempted when the proposal changes. A rerun that
    scores the same record the same way writes no second journal entry, and a
    creator already audited or preselected is not pulled back to SCORED.

    A record outside the profile has no score and no storable proposal —
    ``score_proposal`` accepts four values only — so it lands as REJECTED, with
    the exact proposal kept in the journal entry's payload.
    """
    if record_id is None:
        raise ValueError("a decision needs a record id: no record was found")

    run = result.to_score_run()
    status = _decision_status(result.proposal)
    proposal = _STORABLE_PROPOSAL.get(result.proposal, result.proposal)

    with connection.cursor() as cursor:
        cursor.execute(SELECT_DECISION, (str(record_id),))
        row = cursor.fetchone()
        if row is None:
            raise LookupError(f"record {record_id} does not exist")
        _, previous_proposal = row

        if previous_proposal != proposal:
            cursor.execute(
                SELECT_TRANSITION,
                (
                    str(record_id),
                    status,
                    _justification(result),
                    actor,
                    "SCORING",
                    result.criteria_version,
                    json.dumps(_payload(result)),
                ),
            )

        cursor.execute(
            UPDATE_DECISION,
            (
                run["score"] if run else None,
                run["total_exact"] if run else None,
                run["incomplete"] if run else False,
                proposal,
                result.criteria_version,
                str(record_id),
            ),
        )

    return status


def _decision_status(proposal: str) -> str:
    try:
        return _DECISION_STATUS[proposal]
    except KeyError as error:
        raise ValueError(f"unknown proposal: {proposal!r}") from error


def _justification(result: ScoreResult) -> str:
    """One readable sentence, the same for the journal and for a human."""
    if result.score is None:
        return f"score non calculé : {result.reason or result.proposal}"
    exact = _exact_text(result.total_exact)
    return (
        f"score {result.score} sur 100 ({exact} exact), "
        f"seuil {THRESHOLD} : {result.proposal}"
    )


def _payload(result: ScoreResult) -> dict:
    """What the journal keeps that the columns cannot hold."""
    return {
        "proposal": result.proposal,
        "reason": result.reason,
        "score_exact": _exact_text(result.total_exact),
        "bounds": [
            _exact_text(result.lower_bound),
            _exact_text(result.upper_bound),
        ],
        "incomplete": result.incomplete,
    }


def _exact_text(value: Fraction | None) -> str | None:
    """An exact value as a decimal, for the journal."""
    if value is None:
        return None
    decimal = Decimal(value.numerator) / Decimal(value.denominator)
    return format(decimal.normalize(), "f")


# --- eligibility -------------------------------------------------------------

SELECT_FICHE = "SELECT workflow_status, score FROM record WHERE id = %s"

SELECT_KIND = "SELECT kind, workflow_status, score FROM record WHERE id = %s"

RETIRE_CHECK = """
UPDATE eligibility_check
SET is_current = false
WHERE record_id = %s AND check_type = %s AND is_current
"""

INSERT_CHECK = """
INSERT INTO eligibility_check (
    record_id, check_type, status, reasons, checked_by, payload
) VALUES (%s, %s, %s, %s, %s, %s::jsonb)
RETURNING id
"""

INSERT_ELIGIBILITY_DECISION = """
INSERT INTO eligibility_decision (
    record_id, status, justification, decided_by, criteria_version
) VALUES (%s, %s, %s, %s, %s)
RETURNING id
"""

LINK_DECISION_CHECK = """
INSERT INTO eligibility_decision_check (decision_id, check_id) VALUES (%s, %s)
"""

UPDATE_ELIGIBILITY = """
UPDATE record SET eligibility_status = %s, updated_at = now() WHERE id = %s
"""

INSERT_EXCEPTION_DECISION = """
INSERT INTO eligibility_decision (
    record_id, status, justification, decided_by, criteria_version,
    exception_owner, exception_justification, exception_valid_until
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
RETURNING id
"""


def write_eligibility(
    connection,
    *,
    record_id,
    decision,
    actor: str,
    criteria_version: str = CRITERIA_VERSION,
) -> str | None:
    """Store the checks, the eligibility verdict, and move the fiche.

    The checks are always stored, superseding the previous ones: they are the
    evidence behind the verdict. The verdict row and the ``eligibility_status``
    column exist only when the decision has one — a record held for compliance
    or rejected by a label has no eligibility status, and claiming one would be
    a verdict nobody took.

    The workflow move goes through ``transition_record()``, and only when the
    status actually changes. Returns the event id, or None when the fiche was
    already in that status.
    """
    if record_id is None:
        raise ValueError("an eligibility decision needs a record id")
    if not decision.checks:
        raise ValueError("an eligibility decision needs at least one check")

    with connection.cursor() as cursor:
        cursor.execute(SELECT_FICHE, (str(record_id),))
        row = cursor.fetchone()
        if row is None:
            raise LookupError(f"record {record_id} does not exist")
        status, score = row

        # A fiche that was never scored is not eligible for anything: the
        # regulatory check comes after the score in the journey, and a score
        # cannot be replaced by a check either (H-04).
        if score is None:
            raise ValueError("a record without a score cannot be declared eligible")
        if status == REJECTED:
            raise ValueError("a rejected record is not eligible")

        check_ids = []
        for item in decision.checks:
            cursor.execute(RETIRE_CHECK, (str(record_id), item.check_type))
            cursor.execute(
                INSERT_CHECK,
                (
                    str(record_id),
                    item.check_type,
                    item.status,
                    list(item.reasons),
                    actor,
                    json.dumps({"source_url": item.source_url}),
                ),
            )
            check_ids.append(cursor.fetchone()[0])

        if decision.status is not None:
            cursor.execute(
                INSERT_ELIGIBILITY_DECISION,
                (
                    str(record_id),
                    decision.status,
                    decision.justification,
                    actor,
                    criteria_version,
                ),
            )
            decision_id = cursor.fetchone()[0]
            for check_id in check_ids:
                cursor.execute(LINK_DECISION_CHECK, (decision_id, check_id))
            cursor.execute(UPDATE_ELIGIBILITY, (decision.status, str(record_id)))

        event_id = _move(
            cursor,
            record_id=record_id,
            current=status,
            target=decision.workflow_status,
            justification=decision.justification,
            actor=actor,
            payload={
                "eligibility_status": decision.status,
                "checks": [item.check_type for item in decision.checks],
            },
        )

    return None if event_id is None else str(event_id)


def write_review_decision(
    connection,
    *,
    record_id,
    status: str,
    justification: str,
    actor: str,
    criteria_version: str = CRITERIA_VERSION,
) -> str | None:
    """Close a review with a human verdict, and move the fiche.

    This is the way out of MANUAL_REVIEW, COMPLIANCE_REVIEW and TO_REVIEW, and
    the only one: a fiche under review does not leave it by a new automatic
    score, and H-01 forbids leaving COMPLIANCE_REVIEW without a traced human
    decision. The verdict, its author and its justification are all required.

    No check is written here: a human decision must rest on checks that already
    exist, or on a new search. This function records the decision, not the
    evidence.
    """
    if record_id is None:
        raise ValueError("a review decision needs a record id")
    verdict = (status or "").strip()
    if verdict not in {
        eligibility.ELIGIBLE,
        eligibility.INELIGIBLE,
        eligibility.REGULATORY_PENDING,
    }:
        raise ValueError(f"unknown eligibility verdict: {status!r}")
    reason = (justification or "").strip()
    if not reason:
        raise ValueError("a review decision needs a justification")

    with connection.cursor() as cursor:
        kind, current, score = _read_fiche(cursor, record_id)
        if score is None:
            raise ValueError("a record without a score cannot be declared eligible")
        if current not in eligibility.REVIEW_STATUSES:
            raise ValueError(f"record {record_id} is not under review: {current}")

        cursor.execute(
            INSERT_ELIGIBILITY_DECISION,
            (str(record_id), verdict, reason, actor, criteria_version),
        )
        cursor.execute(UPDATE_ELIGIBILITY, (verdict, str(record_id)))

        target = eligibility.workflow_status_for(verdict, kind)
        event_id = _move(
            cursor,
            record_id=record_id,
            current=current,
            target=target,
            justification=reason,
            actor=actor,
            payload={"eligibility_status": verdict, "checks": []},
        )

    return None if event_id is None else str(event_id)


def write_exception(
    connection,
    *,
    record_id,
    owner: str,
    justification: str,
    valid_until,
    actor: str,
    criteria_version: str = CRITERIA_VERSION,
) -> str | None:
    """Record a signed derogation, and qualify the fiche.

    ``EXCEPTION_APPROVED`` is never a verification (V-22): the owner, the
    justification and the end date are all required, by this function and by the
    schema. The fiche moves to the status a positive verdict would give it, and
    the journal says the decision was an exception, by whom, until when.
    """
    if record_id is None:
        raise ValueError("an exception needs a record id")
    responsible = (owner or "").strip()
    reason = (justification or "").strip()
    if not responsible or not reason or not valid_until:
        raise ValueError("an exception needs an owner, a justification and an end date")

    text = f"dérogation de {responsible}, valable jusqu'au {valid_until} : {reason}"

    with connection.cursor() as cursor:
        kind, current, score = _read_fiche(cursor, record_id)
        if score is None:
            raise ValueError("a record without a score cannot be declared eligible")
        if current == "REJECTED":
            raise ValueError("a rejected record is not eligible")

        cursor.execute(
            INSERT_EXCEPTION_DECISION,
            (
                str(record_id),
                eligibility.EXCEPTION_APPROVED,
                text,
                actor,
                criteria_version,
                responsible,
                reason,
                valid_until,
            ),
        )
        cursor.execute(
            UPDATE_ELIGIBILITY, (eligibility.EXCEPTION_APPROVED, str(record_id))
        )

        target = eligibility.workflow_status_for(eligibility.ELIGIBLE, kind)
        event_id = _move(
            cursor,
            record_id=record_id,
            current=current,
            target=target,
            justification=text,
            actor=actor,
            payload={
                "eligibility_status": eligibility.EXCEPTION_APPROVED,
                "exception_owner": responsible,
                "exception_valid_until": str(valid_until),
                "checks": [],
            },
        )

    return None if event_id is None else str(event_id)


def _read_fiche(cursor, record_id) -> tuple[str, str, int | None]:
    cursor.execute(SELECT_KIND, (str(record_id),))
    row = cursor.fetchone()
    if row is None:
        raise LookupError(f"record {record_id} does not exist")
    return row[0], row[1], row[2]


def _move(
    cursor, *, record_id, current, target, justification, actor, payload
) -> str | None:
    """Ask ``transition_record()`` for a status change, if there is one."""
    if current == target:
        return None
    cursor.execute(
        SELECT_TRANSITION,
        (
            str(record_id),
            target,
            justification,
            actor,
            "ELIGIBILITY",
            None,
            json.dumps(payload),
        ),
    )
    return cursor.fetchone()[0]


def _numeric(value: Fraction | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(value.numerator) / Decimal(value.denominator)
