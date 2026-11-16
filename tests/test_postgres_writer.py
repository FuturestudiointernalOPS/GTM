"""Tests for the PostgreSQL writer, against a fake connection.

No driver and no server: the fake records every statement and its parameters, so
the column list and the values are checked before they ever reach a database.
"""
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
    write_measure,
    write_score,
)
from processing.engagement import EngagementMeasure
from processing.scoring import CreatorMeasures, score_creator

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
