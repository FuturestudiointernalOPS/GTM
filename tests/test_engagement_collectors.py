"""Tests for the platform row normalizers (E3).

The collector layer is tested without network: raw Actor-like rows in, canonical
engagement items out. One end-to-end case hands the Telegram sample to the
measure and then to the score, so the three stages cannot drift apart.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from integrations import engagement_collectors as ec
from processing.engagement import EngagementProfile, measure_engagement
from processing.scoring import CreatorMeasures, score_creator

READ = "2026-11-10T12:00:00+00:00"


def day(days_ago: int) -> str:
    return (datetime.fromisoformat(READ) - timedelta(days=days_ago)).isoformat()


def telegram_rows() -> list[dict]:
    return [
        {"url": "https://t.me/test/1", "published_at": day(1), "views": 12_000, "id": "1"},
        {
            "url": "https://t.me/test/2",
            "published_at": day(2),
            "views": "12 000",
            "pinned": True,
        },
        {"url": "https://t.me/test/3", "published_at": day(3), "id": "3"},
        {
            "url": "https://t.me/test/4",
            "published_at": day(4),
            "views": 5_000,
            "is_ad": True,
        },
        {
            "url": "https://t.me/test/5",
            "published_at": day(5),
            "views": 7_000,
            "views_hidden": True,
        },
    ]


def test_telegram_rows_become_posts_with_exclusions_and_unreadables():
    collection = ec.normalize_items("Telegram", telegram_rows(), read_at=READ)

    assert collection.platform == "telegram"
    assert collection.raw_count == 5
    assert collection.skipped == 0
    assert all(item.read_at == READ for item in collection.items)

    pinned, unreadable, ad, hidden = collection.items[1:]
    assert pinned.exclusion_reason == "PINNED"
    assert pinned.readable is True
    assert pinned.value == 12_000

    assert ad.exclusion_reason == "PAID_AD"
    assert ad.readable is True

    assert unreadable.readable is False
    assert unreadable.value is None
    assert unreadable.exclusion_reason == "UNREADABLE"

    assert hidden.readable is False
    assert hidden.value is None
    assert hidden.exclusion_reason == "UNREADABLE"


def test_vk_video_separates_long_videos_clips_live_and_posts():
    rows = [
        {"url": "https://vk.com/video-1_2", "published_at": day(1), "views": 8_000},
        {"url": "https://vk.com/clip-1_3", "published_at": day(2), "views": 800_000},
        {
            "url": "https://vk.com/video-1_4",
            "published_at": day(3),
            "views": 2_000,
            "is_live": True,
        },
        {
            "url": "https://vk.com/wall-1_5",
            "published_at": day(4),
            "views": 1_000,
            "type": "post",
        },
        {"url": "https://vk.com/shorts-1_6", "published_at": day(5), "views": 9_000},
    ]

    items = ec.normalize_items("VK Video", rows, read_at=READ).items

    assert [item.item_kind for item in items] == [
        "LONG_VIDEO",
        "CLIP",
        "STREAM",
        "POST",
        "SHORT",
    ]
    assert items[1].exclusion_reason == "CLIP"
    assert items[2].exclusion_reason == "LIVE"


def test_rutube_classifies_shorts_clips_and_live():
    rows = [
        {"url": "https://rutube.ru/video/abc/", "published_at": day(1), "views": 5_000},
        {"url": "https://rutube.ru/shorts/def/", "published_at": day(2), "views": 9_000},
        {"url": "https://rutube.ru/clip/ghi/", "published_at": day(3), "views": 8_000},
        {"url": "https://rutube.ru/live/jkl/", "published_at": day(4), "views": 1_000},
    ]

    items = ec.normalize_items("Rutube", rows, read_at=READ).items

    assert [item.item_kind for item in items] == [
        "LONG_VIDEO",
        "SHORT",
        "CLIP",
        "STREAM",
    ]


def test_youtube_reads_nested_counts_and_classifies_formats():
    rows = [
        {
            "url": "https://www.youtube.com/watch?v=a",
            "published_at": day(1),
            "statistics": {"viewCount": "12,345"},
        },
        {
            "url": "https://www.youtube.com/shorts/b",
            "published_at": day(2),
            "views": 900_000,
        },
        {
            "url": "https://www.youtube.com/clip/c",
            "published_at": day(3),
            "views": 8_000,
        },
        {
            "url": "https://www.youtube.com/live/d",
            "published_at": day(4),
            "views": 1_000,
        },
        {
            "url": "https://www.youtube.com/watch?v=e",
            "published_at": day(5),
            "views": 7_000,
            "views_hidden": True,
        },
    ]

    items = ec.normalize_items("YouTube", rows, read_at=READ).items

    assert [item.item_kind for item in items] == [
        "LONG_VIDEO",
        "SHORT",
        "CLIP",
        "STREAM",
        "LONG_VIDEO",
    ]
    assert items[0].value == 12_345
    assert items[4].readable is False
    assert items[4].exclusion_reason == "UNREADABLE"


def test_twitch_uses_concurrency_and_never_replay_views():
    rows = [
        {
            "url": "https://www.twitch.tv/channel",
            "published_at": day(1),
            "average_viewers": 1_200,
            "id": "s1",
        },
        {
            "url": "https://www.twitch.tv/channel",
            "published_at": day(2),
            "views": 9_999,
            "id": "s2",
        },
        {
            "url": "https://www.twitch.tv/videos/123",
            "published_at": day(3),
            "views": 30_000,
            "type": "vod",
        },
        {
            "url": "https://clips.twitch.tv/abc",
            "published_at": day(4),
            "views": 5_000,
            "type": "clip",
        },
    ]

    items = ec.normalize_items("Twitch", rows, read_at=READ).items

    assert items[0].item_kind == "STREAM"
    assert items[0].value == 1_200

    # A stream with only replay views is unreadable: the collector must not
    # silently turn 9 999 VOD views into a live concurrency.
    assert items[1].item_kind == "STREAM"
    assert items[1].value is None
    assert items[1].readable is False
    assert items[1].exclusion_reason == "UNREADABLE"

    assert items[2].item_kind == "VOD"
    assert items[3].item_kind == "CLIP"
    assert items[3].exclusion_reason == "CLIP"


def test_a_row_without_url_or_date_is_skipped():
    rows = [
        {"url": "https://t.me/test/1", "published_at": day(1), "views": 1},
        {"published_at": day(2), "views": 2},
        {"url": "https://t.me/test/3", "views": 3},
    ]

    collection = ec.normalize_items("Telegram", rows, read_at=READ)

    assert collection.raw_count == 3
    assert collection.skipped == 2
    assert len(collection.items) == 1


def test_platform_labels_are_normalized():
    row = {"url": "https://vk.com/video-1_2", "published_at": day(1), "views": 1}

    collection = ec.normalize_items("VK Video", [row], read_at=READ)

    assert collection.platform == "vk_video"


def test_unsupported_platform_is_rejected():
    with pytest.raises(ValueError, match="unsupported"):
        ec.normalize_items("Instagram", [], read_at=READ)


def test_read_at_must_be_an_iso_datetime():
    with pytest.raises(ValueError, match="read_at"):
        ec.normalize_items("Telegram", [], read_at="not-a-date")


def test_collect_with_apify_returns_the_run_handles(monkeypatch):
    row = {"url": "https://t.me/test/1", "published_at": day(1), "views": 12_000}

    def fake_run(actor_id, run_input, **options):
        assert actor_id == "apify/test"
        assert run_input == {"startUrls": ["https://t.me/test"]}
        assert options["max_items"] == 10
        return SimpleNamespace(run_id="run-1", dataset_id="ds-1", items=[row])

    monkeypatch.setattr(ec.apify, "run_actor_result", fake_run)

    collection = ec.collect_with_apify(
        "Telegram",
        "apify/test",
        {"startUrls": ["https://t.me/test"]},
        read_at=READ,
        max_items=10,
    )

    assert collection.run_id == "run-1"
    assert collection.dataset_id == "ds-1"
    assert collection.items[0].value == 12_000


def test_telegram_collection_feeds_the_measure_and_the_score():
    rows = [
        {"url": f"https://t.me/test/{index}", "published_at": day(index), "views": 12_000}
        for index in range(1, 30)
    ]
    rows.append(
        {"url": "https://t.me/test/30", "published_at": day(30), "views": 900_000}
    )

    collection = ec.normalize_items("Telegram", rows, read_at=READ)
    measure = measure_engagement(
        collection.items,
        EngagementProfile(
            main_platform="Telegram", followers=100_000, followers_read_at=READ
        ),
    )

    assert measure.value == 12_000
    assert measure.sample_size == 30
    assert "DISPERSION" in measure.flags

    result = score_creator(
        CreatorMeasures(
            median_views=measure.value,
            followers=100_000,
            engagement_read_at=measure.read_at,
            engagement_sample=measure.sample_size,
            platform="telegram",
        )
    )
    engagement = next(line for line in result.lines if line.criterion == "engagement")
    assert engagement.points == 15


def test_a_negative_value_is_not_hidden_by_the_normalizer():
    row = {"url": "https://t.me/test/1", "published_at": day(1), "views": -1}

    collection = ec.normalize_items("Telegram", [row], read_at=READ)
    item = collection.items[0]

    assert item.readable is True
    assert item.value == -1

    measure = measure_engagement(
        collection.items,
        EngagementProfile(
            main_platform="Telegram", followers=100_000, followers_read_at=READ
        ),
    )
    assert measure.status == "UNKNOWN"
    assert measure.reason == "out_of_domain"


def test_a_pinned_unreadable_row_keeps_both_facts():
    row = {
        "url": "https://t.me/test/1",
        "published_at": day(1),
        "pinned": True,
    }

    item = ec.normalize_items("Telegram", [row], read_at=READ).items[0]

    assert item.readable is False
    assert item.value is None
    assert item.exclusion_reason == "PINNED"
