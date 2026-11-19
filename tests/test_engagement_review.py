"""Tests for the stored-sample replay and the review vocabulary (E5)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

from processing.engagement import (
    VIEWS_PER_ITEM,
    EngagementMeasure,
)
from processing.engagement_review import (
    AUDIT_DISPERSION,
    REVIEW_UNKNOWN,
    REVIEW_UNREADABLE,
    REVIEW_WEAK_SAMPLE,
    item_from_row,
    matches_stored,
    needs_audit,
    recompute_measure,
    review_reasons,
)

READ = "2026-11-10T12:00:00+00:00"
ROOT = Path(__file__).resolve().parent.parent


def sample_row(
    index: int,
    *,
    value=12_000,
    days_ago: int | None = None,
    readable=True,
    reason=None,
    kind="POST",
    read_at=READ,
) -> dict:
    published = datetime.fromisoformat(READ) - timedelta(
        days=index if days_ago is None else days_ago
    )
    return {
        "item_url": f"https://t.me/test/{index}",
        "item_kind": kind,
        "published_at": published.isoformat(),
        "value": value,
        "read_at": read_at,
        "readable": readable,
        "exclusion_reason": reason,
    }


def measure(**overrides) -> EngagementMeasure:
    values = {
        "status": "MEASURED",
        "measure_kind": VIEWS_PER_ITEM,
        "statistic": "MEDIAN",
        "value": Fraction(12_000),
        "sample_size": 30,
        "unreadable_count": 0,
        "window_start": "2026-10-11T12:00:00+00:00",
        "window_end": READ,
        "window_mode": "TIME",
        "flags": (),
        "read_at": READ,
        "sample_hash": "hash",
        "reason": None,
    }
    values.update(overrides)
    return EngagementMeasure(**values)


def test_recompute_replays_the_median_from_stored_rows():
    rows = [sample_row(index) for index in range(1, 30)]
    rows.append(sample_row(30, value=900_000))

    result = recompute_measure(
        rows, platform="Telegram", followers=100_000, read_at=READ
    )

    assert result.status == "MEASURED"
    assert result.value == 12_000
    assert result.sample_size == 30
    assert "DISPERSION" in result.flags
    assert matches_stored(result, status="MEASURED", value=Decimal("12000.0")) is True
    assert matches_stored(result, status="MEASURED", value=13_000) is False


def test_a_datetime_and_decimal_row_is_accepted():
    item = item_from_row(
        {
            "item_url": "https://t.me/test/1",
            "item_kind": "POST",
            "published_at": datetime(2026, 11, 1, 10, tzinfo=UTC),
            "value": Decimal("12000.0"),
            "read_at": datetime.fromisoformat(READ),
            "readable": True,
        },
        platform="Telegram",
    )

    assert item.value == Fraction(12_000)
    assert item.published_at == "2026-11-01T10:00:00+00:00"
    assert item.read_at == READ


def test_review_reasons_follow_the_measure_flags():
    assert review_reasons(measure()) == ()
    assert review_reasons(measure(flags=("UNREADABLE", "WEAK_SAMPLE"))) == (
        REVIEW_UNREADABLE,
        REVIEW_WEAK_SAMPLE,
    )
    assert review_reasons(
        measure(
            status="UNKNOWN",
            value=None,
            flags=("WINDOW_EXTENDED",),
            reason="sample_too_small",
        )
    ) == (REVIEW_UNKNOWN,)


def test_dispersion_is_an_audit_signal_not_a_review():
    result = measure(flags=(AUDIT_DISPERSION,))

    assert needs_audit(result) is True
    assert review_reasons(result) == ()


def test_a_four_item_sample_replays_as_unknown():
    result = recompute_measure(
        [sample_row(index) for index in range(1, 5)],
        platform="Telegram",
        followers=100_000,
        read_at=READ,
    )

    assert result.status == "UNKNOWN"
    assert result.reason == "sample_too_small"
    assert matches_stored(result, status="UNKNOWN", value=None) is True


def test_a_pinned_unreadable_row_is_ignored_by_the_replay():
    rows = [sample_row(index) for index in range(1, 6)]
    rows.append(sample_row(6, value=None, readable=False, reason="PINNED"))

    result = recompute_measure(
        rows, platform="Telegram", followers=100_000, read_at=READ
    )

    assert result.status == "MEASURED"
    assert result.sample_size == 5
    assert result.value == 12_000
    assert result.unreadable_count == 0


def test_a_snapshot_mismatch_is_not_a_median():
    rows = [
        sample_row(index, read_at="2026-11-09T12:00:00+00:00") for index in range(1, 6)
    ]

    result = recompute_measure(
        rows, platform="Telegram", followers=100_000, read_at=READ
    )

    assert result.status == "UNKNOWN"
    assert result.reason == "snapshot_mismatch"
    assert result.value is None


def test_the_review_views_and_reason_column_are_declared():
    fresh = (ROOT / "db" / "postgres" / "001_schema.sql").read_text(encoding="utf-8")
    migration = (ROOT / "db" / "postgres" / "003_engagement.sql").read_text(
        encoding="utf-8"
    )

    for name in (
        "creator_engagement_fiche",
        "engagement_review_queue",
        "engagement_audit_queue",
        "creator_engagement_sample",
    ):
        assert f"VIEW {name}" in fresh
        assert f"VIEW {name}" in migration

    assert "reason                      text" in fresh
    assert "ADD COLUMN IF NOT EXISTS reason text" in migration
