"""Tests for the engagement sample step.

The fetcher is injected, so these tests prove the translation without an actor:
platform from the address, rows in, items stamped with the candidate's read time.
"""

from datetime import datetime, timedelta

import pytest

from workflows.engagement_step import apify_fetcher, creator_sampler
from workflows.record_flow import BUYER, CREATOR
from workflows.record_loop import Candidate

READ = "2026-11-10T12:00:00+00:00"


def candidate(url="https://vk.com/creator", kind=CREATOR):
    return Candidate(kind=kind, record_id="r", source_url=url, text="t", read_at=READ)


def vk_rows(count=30, value=2_000):
    base = datetime.fromisoformat(READ)
    return [
        {
            "url": f"https://vk.com/video-1_{index}",
            "published_at": (base - timedelta(days=index)).isoformat(),
            "views": value,
        }
        for index in range(1, count + 1)
    ]


def test_a_creator_page_gets_its_sample():
    sampler = creator_sampler(lambda platform, url: vk_rows())

    items = sampler(candidate())

    assert len(items) == 30
    assert items[0].read_at == READ
    assert items[0].item_kind == "LONG_VIDEO"


def test_a_buyer_candidate_has_no_sample():
    sampler = creator_sampler(lambda platform, url: vk_rows())

    assert sampler(candidate(kind=BUYER)) == ()


def test_an_out_of_scope_page_has_no_sample():
    sampler = creator_sampler(lambda platform, url: vk_rows())

    assert sampler(candidate(url="https://example.com/x")) == ()


def test_the_platform_comes_from_the_address():
    seen = []

    def fetch(platform, url):
        seen.append(platform)
        return []

    creator_sampler(fetch)(candidate(url="https://t.me/creator"))

    assert seen == ["Telegram"]


# --- the Apify fetcher -------------------------------------------------------


def test_the_actor_receives_the_platform_and_the_url():
    calls = []

    def run(actor_id, payload, *, max_items):
        calls.append((actor_id, payload, max_items))
        return [{"url": "https://vk.com/video-1", "views": 10}]

    fetch = apify_fetcher(
        "apify/vk-scraper",
        {
            "profile": "{url}",
            "platform": "{platform}",
            "nested": ["{url}"],
            "limit": 3,
        },
        max_items=50,
        run=run,
    )

    rows = fetch("VK Video", "https://vk.com/creator")

    assert list(rows) == [{"url": "https://vk.com/video-1", "views": 10}]
    assert calls == [
        (
            "apify/vk-scraper",
            {
                "profile": "https://vk.com/creator",
                "platform": "VK Video",
                "nested": ["https://vk.com/creator"],
                "limit": 3,
            },
            50,
        )
    ]


def test_the_input_can_be_read_from_json_text():
    seen = []

    def run(actor_id, payload, *, max_items):
        seen.append(payload)
        return []

    fetch = apify_fetcher("apify/actor", '{"profile": "{url}"}', run=run)
    fetch("Telegram", "https://t.me/creator")

    assert seen == [{"profile": "https://t.me/creator"}]


def test_without_an_actor_no_sample_is_collected():
    def run(actor_id, payload, *, max_items):
        raise AssertionError("the actor must not run")

    fetch = apify_fetcher(None, run=run)

    assert fetch("Telegram", "https://t.me/creator") == ()


def test_an_input_that_is_not_json_is_refused():
    with pytest.raises(ValueError, match="not valid JSON"):
        apify_fetcher("apify/actor", "{broken")


def test_an_input_that_is_not_an_object_is_refused():
    with pytest.raises(ValueError, match="JSON object"):
        apify_fetcher("apify/actor", "[1, 2]")
