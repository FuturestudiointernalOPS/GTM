"""Tests for the Telegram directory Actor wrapper. No network, no paid run."""
from decimal import Decimal

import pytest

from integrations import apify
from integrations import telegram_directory as td

ROW = {
    "source_directory": "tgstat",
    "listing_id": "blumcrypto",
    "group_name": "Blum: All Crypto - One App",
    "telegram_handle": "blumcrypto",
    "telegram_url": "https://t.me/blumcrypto",
    "description": None,
    "category": "Games & Apps",
    "language": None,
    "country": "global",
    "member_count": 13_323_823,
    "member_growth": None,
    "growth_period": None,
    "average_post_reach": 123_900,
    "citation_index": 3309,
    "monthly_active_users": None,
    "messages_7d": None,
    "rating": None,
    "is_channel": True,
    "source_url": "https://tgstat.com/ratings/channels/games?sort=members",
}

COLLECTED_AT = "2026-11-10T12:00:00+00:00"


def test_build_input_maps_the_actor_field_names():
    payload = td.build_input(
        sources=["tgstat"],
        group_types=["channel"],
        categories=["games"],
        regions=["global"],
        rankings=["members"],
        max_items=20,
        resume_cursor=" cursor-1 ",
        contact="ops@example.com",
        intended_usage="creator discovery",
        improvement_suggestions="add Russia",
    )

    assert payload == {
        "sources": ["tgstat"],
        "groupTypes": ["channel"],
        "categories": ["games"],
        "regions": ["global"],
        "rankings": ["members"],
        "maxItems": 20,
        "resumeCursor": "cursor-1",
        "sp_contact": "ops@example.com",
        "sp_intended_usage": "creator discovery",
        "sp_improvement_suggestions": "add Russia",
    }


def test_empty_filters_are_omitted_to_keep_the_actor_defaults():
    assert td.build_input(sources=[], categories=["  "], max_items=None) == {}


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sources": ["vk"]},
        {"group_types": ["bot"]},
        {"categories": ["fps"]},
        {"regions": ["ru"]},
        {"rankings": ["likes"]},
    ],
)
def test_unknown_filter_values_are_refused_before_a_paid_run(kwargs):
    with pytest.raises(ValueError, match="Unknown"):
        td.build_input(**kwargs)


@pytest.mark.parametrize("value", [0, -1, True, "10"])
def test_max_items_must_be_a_positive_integer(value):
    with pytest.raises(ValueError, match="max_items"):
        td.build_input(max_items=value)


def test_the_cost_ceiling_uses_the_published_price():
    assert td.estimate_max_cost_usd(15) == Decimal("0.0240")
    assert td.estimate_max_cost_usd(1_000) == Decimal("1.6000")


def test_scrape_runs_the_actor_and_returns_both_shapes(monkeypatch):
    seen = {}

    def fake_run(actor_id, run_input, **options):
        seen.update(actor_id=actor_id, run_input=run_input, **options)
        return apify.ActorRunResult(
            run_id="run-9",
            dataset_id="dataset-9",
            key_value_store_id="kv-9",
            items=[ROW],
            output={"resumeCursor": "next-page"},
        )

    monkeypatch.setattr(td.apify, "run_actor_result", fake_run)

    result = td.scrape(
        categories=["games"],
        regions=["global"],
        rankings=["members"],
        max_items=100,
        resume_cursor="previous-page",
    )

    assert seen == {
        "actor_id": td.ACTOR_ID,
        "run_input": {
            "categories": ["games"],
            "regions": ["global"],
            "rankings": ["members"],
            "maxItems": 100,
            "resumeCursor": "previous-page",
        },
        "max_items": 100,
        "wait_seconds": apify.DEFAULT_WAIT_SECONDS,
        "read_output": True,
    }
    assert result.raw_items == [ROW]
    assert result.resume_cursor == "next-page"
    assert result.run_id == "run-9"
    assert result.estimated_max_cost_usd == Decimal("0.1600")
    assert result.candidates[0]["handle"] == "blumcrypto"


def test_normalize_row_builds_the_creator_fields():
    candidate = td.normalize_row(ROW, collected_at=COLLECTED_AT)

    assert candidate == {
        "main_platform": "Telegram",
        "handle": "blumcrypto",
        "platform_url": "https://t.me/blumcrypto",
        "platform_account_id": "blumcrypto",
        "display_name": "Blum: All Crypto - One App",
        "country": "global",
        "content_language": None,
        "followers": 13_323_823,
        "followers_read_at": COLLECTED_AT,
        "source_refs": [
            {
                "directory": "tgstat",
                "url": "https://tgstat.com/ratings/channels/games?sort=members",
                "listing_id": "blumcrypto",
                "consulted_at": COLLECTED_AT,
            }
        ],
        "directory_facts": {
            "category": "Games & Apps",
            "is_channel": True,
            "description": None,
            "member_growth": None,
            "growth_period": None,
            "average_post_reach": 123_900,
            "citation_index": 3309,
            "monthly_active_users": None,
            "messages_7d": None,
            "rating": None,
        },
    }


def test_a_private_listing_keeps_no_invented_handle_or_url():
    candidate = td.normalize_row(
        {**ROW, "telegram_handle": "", "telegram_url": ""},
        collected_at=COLLECTED_AT,
    )

    assert candidate["handle"] is None
    assert candidate["platform_url"] is None
    assert candidate["platform_account_id"] == "blumcrypto"


def test_a_missing_url_is_rebuilt_from_the_handle():
    candidate = td.normalize_row(
        {**ROW, "telegram_handle": "@red", "telegram_url": ""},
        collected_at=COLLECTED_AT,
    )

    assert candidate["handle"] == "red"
    assert candidate["platform_url"] == "https://t.me/red"


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ({"resumeCursor": "abc"}, "abc"),
        ('{"resumeCursor": "abc"}', "abc"),
        ("abc", "abc"),
        ({"data": {"resumeCursor": "nested"}}, "nested"),
        ({"resume_cursor": "snake"}, "snake"),
        (None, None),
        ({}, None),
        ("", None),
    ],
)
def test_resume_cursor_is_read_from_the_output(output, expected):
    assert td.resume_cursor_from(output) == expected
