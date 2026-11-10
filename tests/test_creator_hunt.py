"""Tests for the creator hunt. No network: Exa and Apify are replaced."""
from decimal import Decimal

import pytest

from integrations import telegram_directory
from workflows import creator_hunt
from workflows import search as workflow_search
from workflows.query_pool import Query


def _page(url, title="Profile"):
    return {
        "url": url,
        "title": title,
        "published_date": "2026-01-02",
        "author": None,
        "text": None,
    }


@pytest.fixture
def exa_calls(monkeypatch):
    """Replace Exa and let each test choose what every query returns."""
    calls: list[dict] = []
    answers: dict[str, list[dict]] = {}

    def fake_search(query, **options):
        calls.append({"query": query, **options})
        return answers.get(query, [])

    monkeypatch.setattr(workflow_search.exa, "search", fake_search)
    return calls, answers


def test_hunt_deduplicates_pages_and_labels_platforms(exa_calls):
    calls, answers = exa_calls
    answers["q1"] = [
        _page("https://vk.com/red"),
        _page("https://www.twitch.tv/red"),
    ]
    answers["q2"] = [
        _page("https://vk.com/red"),
        _page("https://t.me/red"),
        _page("https://youtu.be/abc"),
    ]

    result = creator_hunt.hunt(["q1", "q2"], num_results=3)

    assert result["queries"] == ["q1", "q2"]
    assert [
        (page["url"], page["platform"], page["query"]) for page in result["pages"]
    ] == [
        ("https://vk.com/red", "VK Video", "q1"),
        ("https://www.twitch.tv/red", "Twitch", "q1"),
        ("https://t.me/red", "Telegram", "q2"),
        ("https://youtu.be/abc", "YouTube", "q2"),
    ]
    assert result["profiles"] == []
    assert calls[0]["include_domains"] == creator_hunt.ALLOWED_DOMAINS
    assert calls[0]["exclude_domains"] == creator_hunt.EXCLUDED_DOMAINS
    assert calls[0]["num_results"] == 3


def test_pages_outside_the_scope_are_dropped(exa_calls):
    _, answers = exa_calls
    answers["q"] = [
        _page("https://www.instagram.com/red"),
        _page("https://example.com/not-a-creator"),
    ]

    result = creator_hunt.hunt(["q"])

    assert result["pages"] == []


def test_default_queries_are_used_when_none_are_given(exa_calls):
    calls, _ = exa_calls

    result = creator_hunt.hunt()

    assert result["queries"] == list(creator_hunt.DEFAULT_QUERIES)
    assert [call["query"] for call in calls] == list(creator_hunt.DEFAULT_QUERIES)


def test_an_empty_query_list_is_refused(exa_calls):
    with pytest.raises(ValueError, match="At least one query"):
        creator_hunt.hunt(["  ", ""])


def test_actor_rows_are_returned_when_configured(exa_calls, monkeypatch):
    _, answers = exa_calls
    answers["q"] = [_page("https://vk.com/red")]
    seen = {}

    def fake_extract(actor_id, actor_input, **options):
        seen.update(actor_id=actor_id, actor_input=actor_input, **options)
        return [{"handle": "@red", "followers": 42_000}]

    monkeypatch.setattr(creator_hunt, "extract", fake_extract)

    result = creator_hunt.hunt(
        ["q"],
        actor_id="apify/vk-scraper",
        actor_input={"startUrls": ["https://vk.com/red"]},
        max_items=5,
        wait_seconds=30,
    )

    assert result["profiles"] == [{"handle": "@red", "followers": 42_000}]
    assert seen == {
        "actor_id": "apify/vk-scraper",
        "actor_input": {"startUrls": ["https://vk.com/red"]},
        "max_items": 5,
        "wait_seconds": 30,
    }


def test_an_actor_without_its_input_is_refused(exa_calls):
    with pytest.raises(ValueError, match="actor_input"):
        creator_hunt.hunt(["q"], actor_id="apify/vk-scraper")


def test_platform_mapping_does_not_match_look_alike_domains():
    assert creator_hunt.platform_for("https://notvk.com/red") is None
    assert creator_hunt.platform_for("https://vk.com.evil.example/red") is None
    assert creator_hunt.platform_for("https://m.vk.com/red") == "VK Video"
    assert creator_hunt.platform_for("https://rutube.ru/channel/1") == "Rutube"


def test_hunt_plan_keeps_the_pool_id_on_each_page(exa_calls):
    _, answers = exa_calls
    query = Query(
        id="creator.twitch.cs2",
        block="creators.models",
        text="русскоязычный стример по CS2",
        include_domains=("twitch.tv",),
        exclude_text=("казино",),
    )
    answers[query.text] = [_page("https://www.twitch.tv/red")]

    result = creator_hunt.hunt_plan([query])

    assert result["queries"] == ["creator.twitch.cs2"]
    assert result["pages"][0]["query_used"] == "creator.twitch.cs2"
    assert result["pages"][0]["platform"] == "Twitch"
    assert result["profiles"] == []


def test_hunt_telegram_returns_candidates_the_cursor_and_the_cost(monkeypatch):
    fake = telegram_directory.TelegramDirectoryResult(
        raw_items=[{"telegram_handle": "red"}],
        candidates=[{"handle": "red"}],
        resume_cursor="next-page",
        run_id="run-1",
        collected_at="2026-11-10T12:00:00+00:00",
        estimated_max_cost_usd=Decimal("0.0800"),
    )
    seen = {}

    def fake_scrape(**kwargs):
        seen.update(kwargs)
        return fake

    monkeypatch.setattr(telegram_directory, "scrape", fake_scrape)

    result = creator_hunt.hunt_telegram(max_items=50, resume_cursor="previous-page")

    assert result == {
        "profiles": [{"telegram_handle": "red"}],
        "candidates": [{"handle": "red"}],
        "resume_cursor": "next-page",
        "run_id": "run-1",
        "collected_at": "2026-11-10T12:00:00+00:00",
        "estimated_max_cost_usd": "0.0800",
    }
    assert seen == {
        "sources": None,
        "group_types": None,
        "categories": creator_hunt.TELEGRAM_GAMING_CATEGORIES,
        "regions": creator_hunt.TELEGRAM_REGIONS,
        "rankings": creator_hunt.TELEGRAM_RANKINGS,
        "max_items": 50,
        "resume_cursor": "previous-page",
        "wait_seconds": None,
    }
