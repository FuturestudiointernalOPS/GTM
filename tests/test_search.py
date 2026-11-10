"""Tests for per-query search options and query_used attribution."""
import pytest

from workflows import search
from workflows.search import SearchSpec


def _row(url):
    return {
        "url": url,
        "title": "Page",
        "published_date": None,
        "author": None,
        "text": None,
    }


def test_discover_specs_uses_per_query_filters_and_tracks_the_id(monkeypatch):
    calls = []
    answers = {
        "first text": [_row("https://a.example/profile")],
        "second text": [
            _row("https://a.example/profile"),
            _row("https://b.example/profile"),
        ],
    }

    def fake_search(text, **options):
        calls.append({"text": text, **options})
        return answers[text]

    monkeypatch.setattr(search.exa, "search", fake_search)

    pages = search.discover_specs(
        [
            SearchSpec(
                "first text",
                query_id="creator.twitch.cs2",
                include_domains=("twitch.tv",),
                exclude_text=("казино",),
            ),
            SearchSpec(
                "second text",
                query_id="creator.telegram.cs2",
                exclude_domains=("instagram.com",),
            ),
        ],
        num_results=5,
    )

    assert calls[0] == {
        "text": "first text",
        "num_results": 5,
        "include_domains": ("twitch.tv",),
        "exclude_domains": None,
        "exclude_text": ("казино",),
        "start_published_date": None,
        "with_text": False,
    }
    assert calls[1]["exclude_domains"] == ("instagram.com",)
    assert [(page["url"], page["query_used"]) for page in pages] == [
        ("https://a.example/profile", "creator.twitch.cs2"),
        ("https://b.example/profile", "creator.telegram.cs2"),
    ]
    assert pages[0]["query"] == "first text"


def test_a_duplicate_keeps_the_first_query_attribution(monkeypatch):
    def fake_search(text, **options):
        return [_row("https://same.example/profile")]

    monkeypatch.setattr(search.exa, "search", fake_search)

    pages = search.discover_specs(
        [
            SearchSpec("one", query_id="q.1"),
            SearchSpec("two", query_id="q.2"),
        ]
    )

    assert len(pages) == 1
    assert pages[0]["query_used"] == "q.1"


def test_plain_queries_fall_back_to_their_text(monkeypatch):
    def fake_search(text, **options):
        return [_row("https://a.example/profile")]

    monkeypatch.setattr(search.exa, "search", fake_search)

    pages = search.discover(
        ["plain query"],
        include_domains=("vk.com",),
        exclude_text=("читы",),
    )

    assert pages[0]["query_used"] == "plain query"
    assert pages[0]["query"] == "plain query"


def test_an_empty_spec_is_refused(monkeypatch):
    monkeypatch.setattr(search.exa, "search", lambda *args, **kwargs: [])

    with pytest.raises(ValueError, match="must not be empty"):
        search.discover_specs([SearchSpec("   ")])


def test_discover_specs_dispatches_to_serpapi(monkeypatch):
    seen = {}

    def fake_serpapi(text, **options):
        seen.update(text=text, **options)
        return [_row("https://brand.example")]

    monkeypatch.setattr(search.serpapi, "search", fake_serpapi)

    pages = search.discover_specs(
        [
            SearchSpec(
                "q site:example.ru -казино",
                query_id="buyer.ads.esports",
                service="serpapi",
                engine="google",
            )
        ],
        num_results=10,
    )

    assert seen == {
        "text": "q site:example.ru -казино",
        "engine": "google",
        "num_results": 10,
    }
    assert pages[0]["query_used"] == "buyer.ads.esports"


def test_serpapi_refuses_the_exa_only_date_filter():
    with pytest.raises(ValueError, match="start_published_date"):
        search.discover_specs(
            [SearchSpec("q", service="serpapi")],
            start_published_date="2026-01-01",
        )


def test_an_unknown_service_is_refused():
    with pytest.raises(ValueError, match="Unknown search service"):
        search.discover_specs([SearchSpec("q", service="bing")])
