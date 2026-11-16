"""Tests for the engagement sample step.

The fetcher is injected, so these tests prove the translation without an actor:
platform from the address, rows in, items stamped with the candidate's read time.
"""
from datetime import datetime, timedelta

from workflows.engagement_step import creator_sampler
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
