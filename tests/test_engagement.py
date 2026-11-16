"""Tests for the engagement measure (``docs/engagement.md``, M-01 to M-10).

The measure is tested on its own, then handed to the score to prove the two
stages agree on the points. M1 and M2 carry that double check.
"""
from datetime import datetime, timedelta
from fractions import Fraction

from processing.engagement import (
    CONCURRENT_VIEWERS,
    DISPERSION,
    FALLBACK,
    MEASURED,
    UNKNOWN,
    UNREADABLE,
    WEAK_SAMPLE,
    WINDOW_EXTENDED,
    EngagementItem,
    EngagementProfile,
    measure_engagement,
)
from processing.scoring import CreatorMeasures, score_creator

READ = "2026-11-10T12:00:00+00:00"


def profile(platform="telegram", followers=100_000, read_at=READ):
    return EngagementProfile(
        main_platform=platform, followers=followers, followers_read_at=read_at
    )


def item(
    platform="telegram",
    kind="POST",
    value=12_000,
    days_ago=1,
    readable=True,
    reason=None,
):
    published = datetime.fromisoformat(READ) - timedelta(days=days_ago)
    return EngagementItem(
        platform=platform,
        item_url=f"https://example.test/{platform}/{kind}/{days_ago}/{value}",
        item_kind=kind,
        published_at=published.isoformat(),
        value=value,
        read_at=READ,
        readable=readable,
        exclusion_reason=reason,
    )


def items(count, *, start=1, **kwargs):
    return [item(days_ago=start + offset, **kwargs) for offset in range(count)]


def engagement_points(measure, platform, followers=100_000):
    result = score_creator(
        CreatorMeasures(
            median_views=measure.value,
            followers=followers,
            engagement_read_at=measure.read_at,
            engagement_sample=measure.sample_size,
            platform=platform,
        )
    )
    return next(line for line in result.lines if line.criterion == "engagement").points


# --- the ten frozen cases ---------------------------------------------------


def test_m1_the_median_ignores_one_viral_item():
    sample = items(29) + [item(value=900_000, days_ago=30)]

    measure = measure_engagement(sample, profile())

    assert measure.status == MEASURED
    assert measure.value == 12_000
    assert measure.sample_size == 30
    # Mean 41 600 is above twice the median: diagnostic only, never points.
    assert DISPERSION in measure.flags


def test_m2_twitch_counts_live_concurrency_and_refuses_replays():
    streams = items(10, platform="twitch", kind="STREAM", value=1_200)
    replays = items(10, platform="twitch", kind="VOD", value=30_000)

    measure = measure_engagement(streams + replays, profile("twitch"))

    assert measure.value == 1_200
    assert measure.measure_kind == CONCURRENT_VIEWERS
    assert measure.sample_size == 10


def test_m3_four_readable_items_are_not_enough():
    measure = measure_engagement(items(4), profile())

    assert measure.status == UNKNOWN
    assert measure.reason == "sample_too_small"


def test_m4_unreadable_items_are_counted_not_hidden():
    sample = items(6) + [
        item(value=0, days_ago=7, readable=False),
        item(value=0, days_ago=8, readable=False),
    ]

    measure = measure_engagement(sample, profile())

    assert measure.status == MEASURED
    assert measure.sample_size == 6
    assert measure.unreadable_count == 2
    assert WEAK_SAMPLE in measure.flags
    assert UNREADABLE in measure.flags


def test_m5_youtube_falls_back_to_the_wider_window():
    recent = items(3, platform="youtube", kind="LONG_VIDEO")
    older = items(7, platform="youtube", kind="LONG_VIDEO", start=40)

    measure = measure_engagement(recent + older, profile("youtube"))

    assert measure.window_mode == FALLBACK
    assert measure.sample_size == 10
    assert WINDOW_EXTENDED in measure.flags


def test_m6_an_even_sample_gives_an_exact_median():
    values = [9_000, 10_000, 14_000, 20_000, 8_000, 30_000]
    sample = [item(value=value, days_ago=index + 1) for index, value in enumerate(values)]

    measure = measure_engagement(sample, profile())

    assert measure.value == Fraction(12_000)


def test_m7_a_channel_with_only_live_streams_is_unknown():
    sample = items(10, platform="vk_video", kind="STREAM", value=5_000)

    measure = measure_engagement(sample, profile("vk_video"))

    assert measure.status == UNKNOWN
    assert measure.sample_size == 0


def test_m8_more_than_half_unreadable_is_unknown():
    sample = items(4) + [
        item(value=0, days_ago=offset, readable=False) for offset in range(5, 11)
    ]

    measure = measure_engagement(sample, profile())

    assert measure.status == UNKNOWN
    assert measure.reason == "mostly_unreadable"


def test_m9_a_clip_never_enters_the_median():
    videos = items(20, platform="vk_video", kind="LONG_VIDEO", value=8_000)
    clip = item(
        platform="vk_video", kind="CLIP", value=800_000, days_ago=21, reason="CLIP"
    )

    measure = measure_engagement(videos + [clip], profile("vk_video"))

    assert measure.sample_size == 20
    assert measure.value == 8_000


def test_m10_a_pinned_post_is_excluded():
    posts = items(29)
    pinned = item(value=500_000, days_ago=30, reason="PINNED")

    measure = measure_engagement(posts + [pinned], profile())

    assert measure.sample_size == 29
    assert measure.value == 12_000


# --- the measure feeds the score -------------------------------------------


def test_m1_gives_fifteen_points():
    sample = items(29) + [item(value=900_000, days_ago=30)]

    measure = measure_engagement(sample, profile("telegram"))

    assert engagement_points(measure, "telegram") == 15


def test_m2_gives_six_points():
    sample = items(10, platform="twitch", kind="STREAM", value=1_200)

    measure = measure_engagement(sample, profile("twitch"))

    assert engagement_points(measure, "twitch") == 6


# --- snapshot and determinism ----------------------------------------------


def test_one_snapshot_means_one_timestamp():
    measure = measure_engagement(
        items(12), profile(read_at="2026-11-09T12:00:00+00:00")
    )

    assert measure.status == UNKNOWN
    assert measure.reason == "snapshot_mismatch"


def test_the_same_snapshot_gives_the_same_measure():
    sample = items(12)

    assert measure_engagement(sample, profile()) == measure_engagement(
        sample, profile()
    )


def test_items_from_another_platform_are_ignored():
    sample = items(12) + items(
        12, platform="vk_video", kind="LONG_VIDEO", value=99_000
    )

    measure = measure_engagement(sample, profile("telegram"))

    assert measure.sample_size == 12
    assert measure.value == 12_000
