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
from decimal import Decimal
from fractions import Fraction

from config import settings
from processing.engagement import MEASURED, EngagementMeasure
from processing.scoring import CRITERIA_VERSION, ScoreResult


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
        raise PostgresNotConfigured(
            "DATABASE_URL is not set: add it to the .env file"
        )
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


def _numeric(value: Fraction | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(value.numerator) / Decimal(value.denominator)
