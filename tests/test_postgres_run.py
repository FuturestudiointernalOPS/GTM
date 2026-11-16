"""Tests for the PostgreSQL wiring of the weekly run.

The connection is fake: the test checks which statements run, and where the
transaction boundaries fall. A commit placed in the wrong spot either loses a
fiche or keeps a score that should not exist, so the boundaries are the subject.
"""
from fractions import Fraction

import pytest

from processing.engagement import EngagementMeasure
from processing.scoring import CreatorMeasures, score_creator
from workflows.postgres_run import record_sinks
from workflows.record_flow import CREATOR, RecordScore
from workflows.records import CreatorIdentity

READ = "2026-11-10T12:00:00+00:00"


class _Cursor:
    def __init__(self, connection):
        self._connection = connection
        self._row = None

    def execute(self, sql, params=()):
        self._connection.log.append((" ".join(sql.split()), params))
        answers = self._connection._answers
        self._row = answers.pop(0) if answers else None

    def fetchone(self):
        return self._row

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConnection:
    def __init__(self, answers=()):
        self.log = []
        self.commits = 0
        self.rollbacks = 0
        self._answers = list(answers)

    def cursor(self):
        return _Cursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


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


def measure():
    return EngagementMeasure(
        status="MEASURED",
        measure_kind="VIEWS_PER_ITEM",
        statistic="MEDIAN",
        value=Fraction(24_000),
        sample_size=30,
        unreadable_count=0,
        window_start="2026-10-11T12:00:00+00:00",
        window_end=READ,
        window_mode="TIME",
        flags=(),
        read_at=READ,
        sample_hash="abc123",
    )


def record(**overrides):
    values = {
        "kind": CREATOR,
        "result": score_creator(creator()),
        "record_id": "9f1c0000-0000-0000-0000-000000000001",
        "account_id": "9f1c0000-0000-0000-0000-000000000002",
    }
    values.update(overrides)
    return RecordScore(**values)


# --- the store --------------------------------------------------------------


def test_the_store_reads_through_the_same_connection():
    connection = FakeConnection(answers=[("rec-1", "acc-1")])
    store, _, _ = record_sinks(connection)

    keys = store.find_creator(
        CreatorIdentity("VK Video", "creator", "https://vk.com/creator")
    )

    assert keys.record_id == "rec-1"
    assert keys.account_id == "acc-1"
    assert "creator_platform_account" in connection.log[0][0]


# --- the measure ------------------------------------------------------------


def test_a_measure_without_account_writes_nothing():
    connection = FakeConnection()
    _, save_measure, _ = record_sinks(connection)

    assert save_measure(measure(), None) is None
    assert connection.log == []
    assert connection.commits == 0


def test_a_measure_is_written_but_not_committed_on_its_own():
    connection = FakeConnection(answers=[("measure-1",)])
    _, save_measure, _ = record_sinks(connection)

    assert save_measure(measure(), "acc-1") == "measure-1"
    assert "INSERT INTO engagement_measure_run" in connection.log[0][0]
    assert connection.commits == 0


# --- the score --------------------------------------------------------------


def test_a_score_commits_the_pending_fiches_then_writes_and_commits():
    connection = FakeConnection(answers=[("run-1",)])
    _, _, write = record_sinks(connection)

    assert write(record()) == "run-1"

    assert connection.commits == 2
    assert connection.rollbacks == 0
    assert "INSERT INTO score_run" in connection.log[0][0]
    assert len(connection.log) == 1 + 6


def test_a_rejected_record_commits_the_fiche_and_rolls_back_the_score():
    connection = FakeConnection()
    _, _, write = record_sinks(connection)

    assert write(record(result=score_creator(creator(gaming_share=Fraction(0))))) is None

    # The fiche and the measure are kept; the score is not written at all.
    assert connection.commits == 1
    assert connection.rollbacks == 1
    assert connection.log == []


def test_a_score_without_fiche_rolls_back_and_says_so():
    connection = FakeConnection()
    _, _, write = record_sinks(connection)

    with pytest.raises(ValueError, match="record id"):
        write(record(record_id=None))

    assert connection.rollbacks == 1
    assert connection.commits == 1
