"""Tests for the PostgreSQL writer, against a fake connection.

No driver and no server: the fake records every statement and its parameters, so
the column list and the values are checked before they ever reach a database.
"""
import json
import re
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pytest

from config import settings
from integrations.postgres import (
    INSERT_LINE,
    INSERT_MEASURE,
    INSERT_RUN,
    PostgresNotConfigured,
    connect,
    is_configured,
    write_decision,
    write_eligibility,
    write_exception,
    write_measure,
    write_review_decision,
    write_score,
)
from processing.eligibility import (
    NOT_FOUND,
    VERIFIED,
    CreatorVerification,
    EligibilityDecision,
    decide_creator,
)
from processing.engagement import EngagementMeasure
from processing.scoring import (
    QUALIFIED,
    CreatorMeasures,
    ScoreResult,
    score_creator,
)

DDL = Path(__file__).resolve().parent.parent / "db" / "postgres" / "001_schema.sql"
READ = "2026-11-10T12:00:00+00:00"


class _Cursor:
    def __init__(self, log, ids):
        self._log = log
        self._ids = ids
        self._last = None

    def execute(self, sql, params=()):
        self._log.append((" ".join(sql.split()), params))
        if "RETURNING id" in sql:
            self._last = next(self._ids)

    def fetchone(self):
        return (self._last,)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConnection:
    def __init__(self, ids=("run-1",)):
        self.log = []
        self._ids = iter(ids)

    def cursor(self):
        return _Cursor(self.log, self._ids)


def creator(**overrides):
    values = {
        "gaming_share": Fraction(60),
        "gaming_window": 30,
        "median_views": 2_000,
        "followers": 25_000,
        "engagement_read_at": READ,
        "engagement_sample": 30,
        "engagement_measure_run_id": "measure-1",
        "published_last_30_days": 7,
        "ad_contact": True,
        "past_labeled_ads": False,
        "platform": "vk_video",
        "russian_share": Fraction(70),
        "comment_sample": 50,
    }
    values.update(overrides)
    return CreatorMeasures(**values)


def measure(**overrides):
    values = {
        "status": "MEASURED",
        "measure_kind": "VIEWS_PER_ITEM",
        "statistic": "MEDIAN",
        "value": Fraction(24_000),
        "sample_size": 30,
        "unreadable_count": 0,
        "window_start": "2026-10-11T12:00:00+00:00",
        "window_end": READ,
        "window_mode": "TIME",
        "flags": ("DISPERSION",),
        "read_at": READ,
        "sample_hash": "abc123",
    }
    values.update(overrides)
    return EngagementMeasure(**values)


def insert_columns(statement: str) -> set[str]:
    header = statement.split("VALUES")[0]
    inside = header[header.index("(") + 1 : header.rindex(")")]
    return {part.strip() for part in inside.split(",")}


def ddl_columns(table: str) -> set[str]:
    block = re.search(rf"CREATE TABLE {table} \((.*?)\n\);", DDL.read_text(), re.DOTALL)
    assert block, f"{table} is missing from the schema"
    found: set[str] = set()
    for raw in block.group(1).splitlines():
        text = raw.strip()
        if not text or text.startswith("--"):
            continue
        word = text.split()[0].rstrip(",")
        if word.upper() in {"CONSTRAINT", "PRIMARY", "UNIQUE", "CHECK", "FOREIGN"}:
            continue
        if re.fullmatch(r"[a-z_][a-z0-9_]*", word):
            found.add(word)
    return found


# --- the score --------------------------------------------------------------


def test_a_score_writes_one_run_and_its_lines():
    connection = FakeConnection()

    run_id = write_score(
        connection,
        record_id="rec-1",
        result=score_creator(creator()),
        computed_by="test",
    )

    assert run_id == "run-1"
    assert len(connection.log) == 1 + 6

    sql, params = connection.log[0]
    assert "INSERT INTO score_run" in sql
    assert params[0] == "rec-1"
    assert params[2] == 79
    assert params[3] == "79.875"
    assert params[4] is False

    lines = connection.log[1:]
    assert all("INSERT INTO score_line" in sql for sql, _ in lines)
    assert all(params[0] == "run-1" for _, params in lines)

    engagement = next(params for _, params in lines if params[1] == "engagement")
    assert engagement[7] == "measure-1"
    assert engagement[8]


def test_an_excluded_record_writes_nothing():
    connection = FakeConnection()

    run_id = write_score(
        connection,
        record_id="rec-1",
        result=score_creator(creator(gaming_share=Fraction(0))),
        computed_by="test",
    )

    assert run_id is None
    assert connection.log == []


def test_the_insert_columns_exist_in_the_schema():
    assert insert_columns(INSERT_RUN) <= ddl_columns("score_run")
    assert insert_columns(INSERT_LINE) <= ddl_columns("score_line")
    assert insert_columns(INSERT_MEASURE) <= ddl_columns("engagement_measure_run")


# --- the measure ------------------------------------------------------------


def test_a_measure_writes_one_row():
    connection = FakeConnection(ids=("measure-9",))

    measure_id = write_measure(
        connection,
        account_id="account-1",
        measure=measure(),
        computed_by="test",
    )

    assert measure_id == "measure-9"
    assert len(connection.log) == 1
    _, params = connection.log[0]
    assert params[0] == "account-1"
    assert params[2] == "MEASURED"
    assert params[5] == Decimal(24_000)
    assert params[13] == ["DISPERSION"]


def test_a_fractional_median_is_written_as_a_decimal():
    connection = FakeConnection(ids=("measure-9",))

    write_measure(
        connection,
        account_id="account-1",
        measure=measure(value=Fraction(24_001, 2)),
        computed_by="test",
    )

    assert connection.log[0][1][5] == Decimal("12000.5")


def test_a_measure_without_kind_writes_nothing():
    connection = FakeConnection()

    measure_id = write_measure(
        connection,
        account_id="account-1",
        measure=measure(measure_kind=None),
        computed_by="test",
    )

    assert measure_id is None
    assert connection.log == []


# --- the decision ------------------------------------------------------------


class _DecisionCursor:
    def __init__(self, connection):
        self._connection = connection
        self._row = None

    def execute(self, sql, params=()):
        normalized = " ".join(sql.split())
        self._connection.log.append((normalized, params))
        if "SELECT workflow_status, score_proposal FROM record" in normalized:
            if not self._connection.exists:
                self._row = None
            else:
                self._row = (self._connection.status, self._connection.proposal)
        elif "SELECT transition_record" in normalized:
            self._row = ("event-1",)
        else:
            self._row = None

    def fetchone(self):
        return self._row

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class DecisionConnection:
    def __init__(
        self, status="NEW", proposal=None, exists=True, run_id="rec-1"
    ):
        self.log = []
        self.status = status
        self.proposal = proposal
        self.exists = exists
        self.run_id = run_id

    def cursor(self):
        return _DecisionCursor(self)


def decision(connection, result, record_id="rec-1"):
    return write_decision(
        connection, record_id=record_id, result=result, actor="test"
    )


def transition(connection):
    return next(
        (sql, params)
        for sql, params in connection.log
        if "SELECT transition_record" in sql
    )


def update(connection):
    return next(
        params for sql, params in connection.log if sql.startswith("UPDATE record")
    )


def test_a_preselected_creator_stops_at_scored():
    connection = DecisionConnection()

    assert decision(connection, score_creator(creator())) == "SCORED"

    _, params = transition(connection)
    assert params[1] == "SCORED"
    assert params[2] == "score 79 sur 100 (79.875 exact), seuil 70 : PRESELECTED"
    assert params[3] == "test"
    assert params[4] == "SCORING"

    payload = json.loads(params[6])
    assert payload["proposal"] == "PRESELECTED"
    assert payload["score_exact"] == "79.875"
    assert payload["bounds"] == ["79.875", "79.875"]
    assert payload["incomplete"] is False

    assert update(connection) == (
        79,
        "79.875",
        False,
        "PRESELECTED",
        "1.4",
        "rec-1",
    )


def test_the_status_is_changed_through_the_schema_function_only():
    connection = DecisionConnection()

    decision(connection, score_creator(creator()))

    statements = [sql for sql, _ in connection.log]
    assert any(sql.startswith("SELECT transition_record") for sql in statements)
    assert not any("SET workflow_status" in sql for sql in statements)


def test_a_rejected_creator_moves_to_rejected_without_a_score():
    connection = DecisionConnection()

    result = score_creator(creator(gaming_share=Fraction(0)))
    assert decision(connection, result) == "REJECTED"

    _, params = transition(connection)
    assert params[1] == "REJECTED"
    assert params[2] == "score non calculé : no_gaming_content"

    assert update(connection) == (None, None, False, "REJECTED", "1.4", "rec-1")


def test_a_creator_out_of_profile_keeps_its_label_in_the_journal():
    connection = DecisionConnection()

    result = score_creator(creator(followers=1_000))
    assert result.score is None
    assert decision(connection, result) == "REJECTED"

    _, params = transition(connection)
    payload = json.loads(params[6])
    assert payload["proposal"] == "OUT_OF_PROFILE"

    # score_proposal has no OUT_OF_PROFILE value, so the fiche says REJECTED.
    assert update(connection)[3] == "REJECTED"


def test_a_qualified_buyer_is_stored_as_qualified():
    connection = DecisionConnection()
    result = ScoreResult(
        proposal=QUALIFIED,
        score=75,
        total_exact=Fraction(75),
        lower_bound=Fraction(75),
        upper_bound=Fraction(75),
        incomplete=False,
        lines=(),
    )

    assert decision(connection, result) == "SCORED"

    assert transition(connection)[1][1] == "SCORED"
    assert update(connection)[3] == "QUALIFIED"


def test_a_rerun_with_the_same_proposal_writes_no_journal_entry():
    connection = DecisionConnection(status="PRESELECTED", proposal="PRESELECTED")

    assert decision(connection, score_creator(creator())) == "SCORED"

    statements = [sql for sql, _ in connection.log]
    assert not any("SELECT transition_record" in sql for sql in statements)
    assert any(sql.startswith("UPDATE record") for sql in statements)


def test_a_decision_on_a_missing_record_raises():
    connection = DecisionConnection(exists=False)

    with pytest.raises(LookupError):
        decision(connection, score_creator(creator()))

    assert not any(sql.startswith("UPDATE record") for sql, _ in connection.log)


def test_a_decision_without_a_record_id_raises():
    connection = DecisionConnection()

    with pytest.raises(ValueError, match="record id"):
        decision(connection, score_creator(creator()), record_id=None)

    assert connection.log == []


# --- eligibility -------------------------------------------------------------


class _EligibilityCursor:
    def __init__(self, connection):
        self._connection = connection
        self._row = None

    def execute(self, sql, params=()):
        normalized = " ".join(sql.split())
        self._connection.log.append((normalized, params))
        self._row = self._connection.answer(normalized)

    def fetchone(self):
        return self._row

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class EligibilityConnection:
    def __init__(self, status="SCORED", score=79, exists=True, kind="CREATOR"):
        self.log = []
        self.status = status
        self.score = score
        self.exists = exists
        self.kind = kind
        self.ids = 0

    def cursor(self):
        return _EligibilityCursor(self)

    def answer(self, sql):
        if "SELECT kind, workflow_status, score FROM record" in sql:
            return (self.kind, self.status, self.score) if self.exists else None
        if "SELECT workflow_status, score FROM record" in sql:
            return (self.status, self.score) if self.exists else None
        if "SELECT transition_record" in sql:
            return ("event-9",)
        if "RETURNING id" in sql:
            self.ids += 1
            return (f"id-{self.ids}",)
        return None


def creator_verification(**overrides):
    values = {
        "platform_covered": True,
        "followers": 25_000,
        "foreign_agent_label": False,
        "rkn_status": VERIFIED,
        "sanction_status": NOT_FOUND,
    }
    values.update(overrides)
    return CreatorVerification(**values)


def statements(connection):
    return [sql for sql, _ in connection.log]


def transition_of(connection):
    return next(
        params
        for sql, params in connection.log
        if "SELECT transition_record" in sql
    )


def test_an_eligible_creator_moves_from_scored_to_preselected():
    connection = EligibilityConnection()
    decision = decide_creator(creator_verification())

    event_id = write_eligibility(
        connection, record_id="rec-1", decision=decision, actor="verification"
    )

    assert event_id == "event-9"

    params = transition_of(connection)
    assert params[1] == "PRESELECTED"
    assert params[3] == "verification"
    assert params[4] == "ELIGIBILITY"
    assert json.loads(params[6])["eligibility_status"] == "ELIGIBLE"

    update = next(
        params for sql, params in connection.log if "SET eligibility_status" in sql
    )
    assert update == ("ELIGIBLE", "rec-1")


def test_an_ineligible_creator_moves_to_ineligible():
    connection = EligibilityConnection()
    decision = decide_creator(creator_verification(rkn_status=NOT_FOUND))

    write_eligibility(
        connection, record_id="rec-1", decision=decision, actor="verification"
    )

    assert transition_of(connection)[1] == "INELIGIBLE"
    assert json.loads(transition_of(connection)[6])["eligibility_status"] == (
        "INELIGIBLE"
    )


def test_a_compliance_hold_stores_checks_but_no_verdict():
    connection = EligibilityConnection()
    decision = decide_creator(creator_verification(sanction_status=VERIFIED))

    write_eligibility(
        connection, record_id="rec-1", decision=decision, actor="verification"
    )

    assert decision.status is None
    assert any("INSERT INTO eligibility_check" in sql for sql in statements(connection))
    assert not any(
        "INSERT INTO eligibility_decision " in sql for sql in statements(connection)
    )
    assert not any("SET eligibility_status" in sql for sql in statements(connection))
    assert transition_of(connection)[1] == "COMPLIANCE_REVIEW"


def test_a_previous_check_of_the_same_type_is_retired():
    connection = EligibilityConnection()
    decision = decide_creator(creator_verification())

    write_eligibility(
        connection, record_id="rec-1", decision=decision, actor="verification"
    )

    kinds = [
        "retire" if "is_current = false" in sql else "insert"
        for sql in statements(connection)
        if "is_current = false" in sql or "INSERT INTO eligibility_check" in sql
    ]
    assert kinds[:4] == ["retire", "insert", "retire", "insert"]


def test_the_checks_are_linked_to_the_verdict():
    connection = EligibilityConnection()
    decision = decide_creator(creator_verification())

    write_eligibility(
        connection, record_id="rec-1", decision=decision, actor="verification"
    )

    links = [
        params
        for sql, params in connection.log
        if "INSERT INTO eligibility_decision_check" in sql
    ]
    assert len(links) == len(decision.checks)
    # The verdict row is written after the checks, so it takes the next id.
    assert all(params[0] == f"id-{len(decision.checks) + 1}" for params in links)


def test_a_fiche_already_in_that_status_writes_no_event():
    connection = EligibilityConnection(status="PRESELECTED")
    decision = decide_creator(creator_verification())

    event_id = write_eligibility(
        connection, record_id="rec-1", decision=decision, actor="verification"
    )

    assert event_id is None
    assert not any("SELECT transition_record" in sql for sql in statements(connection))


def test_a_scoreless_fiche_cannot_be_declared_eligible():
    connection = EligibilityConnection(score=None)
    decision = decide_creator(creator_verification())

    with pytest.raises(ValueError, match="without a score"):
        write_eligibility(
            connection, record_id="rec-1", decision=decision, actor="verification"
        )

    assert not any("INSERT INTO eligibility_check" in sql for sql in statements(connection))


def test_a_rejected_fiche_is_not_eligible():
    connection = EligibilityConnection(status="REJECTED")
    decision = decide_creator(creator_verification())

    with pytest.raises(ValueError, match="rejected"):
        write_eligibility(
            connection, record_id="rec-1", decision=decision, actor="verification"
        )


def test_an_eligibility_decision_needs_a_check():
    connection = EligibilityConnection()
    empty = EligibilityDecision(
        status="ELIGIBLE", workflow_status="PRESELECTED", justification="x"
    )

    with pytest.raises(ValueError, match="at least one check"):
        write_eligibility(
            connection, record_id="rec-1", decision=empty, actor="verification"
        )


def test_a_missing_record_raises():
    connection = EligibilityConnection(exists=False)
    decision = decide_creator(creator_verification())

    with pytest.raises(LookupError):
        write_eligibility(
            connection, record_id="rec-1", decision=decision, actor="verification"
        )


def test_the_eligibility_insert_columns_exist_in_the_schema():
    from integrations.postgres import (
        INSERT_CHECK,
        INSERT_ELIGIBILITY_DECISION,
        INSERT_EXCEPTION_DECISION,
        LINK_DECISION_CHECK,
    )

    assert insert_columns(INSERT_CHECK) <= ddl_columns("eligibility_check")
    assert insert_columns(INSERT_ELIGIBILITY_DECISION) <= ddl_columns(
        "eligibility_decision"
    )
    assert insert_columns(INSERT_EXCEPTION_DECISION) <= ddl_columns(
        "eligibility_decision"
    )
    assert insert_columns(LINK_DECISION_CHECK) <= ddl_columns(
        "eligibility_decision_check"
    )


# --- the way out of a review -------------------------------------------------


REASON = "registre consulté à la main : page inscrite le 12 novembre"


def verdict_of(connection):
    return next(
        params
        for sql, params in connection.log
        if "INSERT INTO eligibility_decision " in sql
        and "exception_owner" not in sql
    )


def test_a_review_outcome_closes_the_review_with_a_human_verdict():
    connection = EligibilityConnection(status="MANUAL_REVIEW")

    event = write_review_decision(
        connection,
        record_id="rec-1",
        status="ELIGIBLE",
        justification=REASON,
        actor="analyst",
    )

    assert event == "event-9"
    assert verdict_of(connection)[1] == "ELIGIBLE"
    assert verdict_of(connection)[3] == "analyst"

    params = transition_of(connection)
    assert params[1] == "PRESELECTED"
    assert params[2] == REASON
    assert params[3] == "analyst"

    update = next(
        params for sql, params in connection.log if "SET eligibility_status" in sql
    )
    assert update == ("ELIGIBLE", "rec-1")


def test_a_review_outcome_for_a_buyer_qualifies():
    connection = EligibilityConnection(status="TO_REVIEW", kind="BUYER")

    write_review_decision(
        connection,
        record_id="rec-1",
        status="ELIGIBLE",
        justification=REASON,
        actor="analyst",
    )

    assert transition_of(connection)[1] == "QUALIFIED"


def test_a_confirmed_compliance_hit_makes_the_fiche_ineligible():
    connection = EligibilityConnection(status="COMPLIANCE_REVIEW")

    write_review_decision(
        connection,
        record_id="rec-1",
        status="INELIGIBLE",
        justification="correspondance confirmée par l'analyste",
        actor="compliance",
    )

    assert transition_of(connection)[1] == "INELIGIBLE"


def test_a_review_decision_is_refused_outside_a_review():
    connection = EligibilityConnection(status="SCORED")

    with pytest.raises(ValueError, match="not under review"):
        write_review_decision(
            connection,
            record_id="rec-1",
            status="ELIGIBLE",
            justification=REASON,
            actor="analyst",
        )

    assert [sql for sql, _ in connection.log] == [
        "SELECT kind, workflow_status, score FROM record WHERE id = %s"
    ]


def test_a_review_decision_needs_a_justification():
    connection = EligibilityConnection(status="MANUAL_REVIEW")

    with pytest.raises(ValueError, match="justification"):
        write_review_decision(
            connection,
            record_id="rec-1",
            status="ELIGIBLE",
            justification="  ",
            actor="analyst",
        )

    assert connection.log == []


def test_a_review_decision_refuses_an_unknown_verdict():
    connection = EligibilityConnection(status="MANUAL_REVIEW")

    with pytest.raises(ValueError, match="unknown eligibility verdict"):
        write_review_decision(
            connection,
            record_id="rec-1",
            status="MAYBE",
            justification=REASON,
            actor="analyst",
        )


def test_a_review_decision_on_an_unscored_fiche_is_refused():
    connection = EligibilityConnection(status="MANUAL_REVIEW", score=None)

    with pytest.raises(ValueError, match="without a score"):
        write_review_decision(
            connection,
            record_id="rec-1",
            status="ELIGIBLE",
            justification=REASON,
            actor="analyst",
        )


# --- the exception -----------------------------------------------------------


def test_an_exception_qualifies_the_fiche_and_keeps_its_terms():
    connection = EligibilityConnection(status="INELIGIBLE")

    event = write_exception(
        connection,
        record_id="rec-1",
        owner="Direction",
        justification="partenariat stratégique signé",
        valid_until="2027-03-31",
        actor="admin",
    )

    assert event == "event-9"

    _, params = next(
        (sql, params)
        for sql, params in connection.log
        if "exception_owner" in sql
    )
    assert params[1] == "EXCEPTION_APPROVED"
    assert params[5] == "Direction"
    assert params[6] == "partenariat stratégique signé"
    assert params[7] == "2027-03-31"

    update = next(
        params for sql, params in connection.log if "SET eligibility_status" in sql
    )
    assert update == ("EXCEPTION_APPROVED", "rec-1")

    moved = transition_of(connection)
    assert moved[1] == "PRESELECTED"
    assert "Direction" in moved[2]
    assert "2027-03-31" in moved[2]
    assert json.loads(moved[6])["exception_owner"] == "Direction"


def test_an_exception_needs_its_three_terms():
    for missing in (
        {"owner": " "},
        {"justification": ""},
        {"valid_until": None},
    ):
        connection = EligibilityConnection(status="INELIGIBLE")
        terms = {
            "owner": "Direction",
            "justification": "partenariat",
            "valid_until": "2027-03-31",
        }
        terms.update(missing)

        with pytest.raises(ValueError, match="owner|justification|end date"):
            write_exception(
                connection, record_id="rec-1", actor="admin", **terms
            )

        assert connection.log == []


def test_an_exception_is_refused_on_a_rejected_fiche():
    connection = EligibilityConnection(status="REJECTED")

    with pytest.raises(ValueError, match="rejected"):
        write_exception(
            connection,
            record_id="rec-1",
            owner="Direction",
            justification="partenariat",
            valid_until="2027-03-31",
            actor="admin",
        )


# --- the connection factory -------------------------------------------------


class FakeDriver:
    def __init__(self):
        self.dsn = None

    def connect(self, dsn):
        self.dsn = dsn
        return "connection"


def test_connect_uses_the_given_address():
    driver = FakeDriver()

    assert connect("postgresql://db", driver=driver) == "connection"
    assert driver.dsn == "postgresql://db"


def test_connect_reads_the_setting(monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql://from-env")
    driver = FakeDriver()

    connect(driver=driver)

    assert driver.dsn == "postgresql://from-env"


def test_connect_without_address_refuses(monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_URL", "")

    with pytest.raises(PostgresNotConfigured):
        connect(driver=FakeDriver())


def test_is_configured_follows_the_setting(monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_URL", "")
    assert is_configured() is False

    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql://x")
    assert is_configured() is True
