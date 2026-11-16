"""Contract between the score record and the PostgreSQL score tables.

The DDL is the source of truth: the serializer must not invent a column, must
fill every column the schema declares, and must respect its checks. No database
is needed; the schema file is read directly, so the test fails as soon as one
side moves without the other.
"""
import re
from fractions import Fraction
from pathlib import Path

from processing.scoring import (
    BuyerMeasures,
    CreatorMeasures,
    score_buyer,
    score_creator,
)

DDL = Path(__file__).resolve().parent.parent / "db" / "postgres" / "001_schema.sql"

RUN_KEYS = {
    "criteria_version",
    "score",
    "total_exact",
    "incomplete",
    "bounds_lower",
    "bounds_upper",
    "proposal",
}

LINE_KEYS = {
    "criterion_code",
    "measure",
    "status",
    "points_exact",
    "points_max",
    "blocking",
    "reason",
}


def creator(**overrides):
    values = {
        "gaming_share": Fraction(60),
        "gaming_window": 30,
        "median_views": 2_000,
        "followers": 25_000,
        "engagement_read_at": "2026-11-10T00:00:00+00:00",
        "engagement_sample": 30,
        "published_last_30_days": 7,
        "ad_contact": True,
        "past_labeled_ads": False,
        "platform": "vk_video",
        "russian_share": Fraction(70),
        "comment_sample": 50,
    }
    values.update(overrides)
    return CreatorMeasures(**values)


def buyer(**overrides):
    values = {
        "creators_paid": 1,
        "gaming_core": True,
        "decision_maker": "named_verified",
        "employees": 250,
        "recent_event": True,
    }
    values.update(overrides)
    return BuyerMeasures(**values)


def schema() -> str:
    return DDL.read_text(encoding="utf-8")


def columns(table: str) -> set[str]:
    block = re.search(rf"CREATE TABLE {table} \((.*?)\n\);", schema(), re.DOTALL)
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


def allowed_proposals() -> set[str]:
    block = re.search(
        r"proposal\s+text NOT NULL CHECK \(proposal IN \((.*?)\)\)",
        schema(),
        re.DOTALL,
    )
    assert block, "the proposal check is missing from the schema"
    return set(re.findall(r"'([A-Z_]+)'", block.group(1)))


def test_the_score_run_row_only_uses_declared_columns():
    row = score_creator(creator()).to_score_run()

    assert row is not None
    assert set(row) == RUN_KEYS
    assert set(row) <= columns("score_run")


def test_the_score_line_rows_only_use_declared_columns():
    lines = score_creator(creator()).to_score_lines()

    assert len(lines) == 6
    for line in lines:
        assert set(line) == LINE_KEYS
        assert set(line) <= columns("score_line")


def test_every_line_fills_the_not_null_columns():
    for line in score_creator(creator()).to_score_lines():
        assert line["points_exact"] != ""
        assert line["reason"]
        assert line["status"] in {"MEASURED", "UNKNOWN"}
        assert 0 <= float(line["points_max"])


def test_an_unmeasured_line_is_a_zero_with_an_unknown_status():
    lines = score_creator(creator(published_last_30_days=None)).to_score_lines()
    activity = next(line for line in lines if line["criterion_code"] == "activity")

    assert activity["status"] == "UNKNOWN"
    assert activity["points_exact"] == "0"
    assert activity["reason"]


def test_the_proposals_are_accepted_by_the_schema():
    results = [
        score_creator(creator()),
        score_creator(creator(published_last_30_days=None)),
        score_creator(creator(gaming_share=None)),
        score_buyer(buyer()),
        score_buyer(buyer(decision_maker=None)),
    ]

    for result in results:
        assert result.proposal in allowed_proposals()


def test_the_score_is_an_integer_between_zero_and_one_hundred():
    for result in (score_creator(creator()), score_buyer(buyer())):
        row = result.to_score_run()
        assert row is not None
        assert isinstance(row["score"], int)
        assert 0 <= row["score"] <= 100


def test_the_bounds_follow_the_schema_rule():
    complete = score_creator(creator()).to_score_run()
    incomplete = score_creator(
        creator(published_last_30_days=None)
    ).to_score_run()

    assert complete is not None and incomplete is not None
    assert complete["bounds_lower"] == complete["total_exact"]
    assert complete["bounds_upper"] == complete["total_exact"]
    assert incomplete["incomplete"] is True
    assert incomplete["bounds_lower"] != incomplete["bounds_upper"]


def test_an_excluded_record_writes_no_score_run():
    # An elimination is a decision, not a score of zero.
    excluded = score_creator(creator(gaming_share=Fraction(0)))
    out_of_profile = score_creator(creator(followers=0, median_views=None))

    assert excluded.to_score_run() is None
    assert excluded.to_score_lines() == []
    assert out_of_profile.to_score_run() is None
    assert out_of_profile.to_score_lines() == []
