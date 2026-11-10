"""Tests for the buyer hunt. No network: Exa and Apify are replaced."""
import pytest

from workflows import buyer_hunt
from workflows import search as workflow_search
from workflows.query_pool import Query


def _page(url, title="Company"):
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


def test_hunt_uses_the_defaults_and_excludes_social_platforms(exa_calls):
    calls, answers = exa_calls
    answers[buyer_hunt.DEFAULT_QUERIES[0]] = [_page("https://studio.example")]

    result = buyer_hunt.hunt(num_results=4)

    assert result["queries"] == list(buyer_hunt.DEFAULT_QUERIES)
    assert result["pages"] == [
        {
            "url": "https://studio.example",
            "title": "Company",
            "published_date": "2026-01-02",
            "author": None,
            "text": None,
            "query": buyer_hunt.DEFAULT_QUERIES[0],
            "query_used": buyer_hunt.DEFAULT_QUERIES[0],
        }
    ]
    assert calls[0]["include_domains"] is None
    assert calls[0]["exclude_domains"] == buyer_hunt.EXCLUDED_DOMAINS
    assert calls[0]["num_results"] == 4


def test_hunt_deduplicates_pages_across_queries(exa_calls):
    _, answers = exa_calls
    answers["q1"] = [_page("https://studio.example")]
    answers["q2"] = [_page("https://studio.example"), _page("https://hardware.example")]

    result = buyer_hunt.hunt(["q1", "q2"])

    assert [(page["url"], page["query"]) for page in result["pages"]] == [
        ("https://studio.example", "q1"),
        ("https://hardware.example", "q2"),
    ]


def test_actor_rows_are_returned_when_configured(exa_calls, monkeypatch):
    _, answers = exa_calls
    answers["q"] = [_page("https://studio.example")]
    seen = {}

    def fake_extract(actor_id, actor_input, **options):
        seen.update(actor_id=actor_id, actor_input=actor_input, **options)
        return [{"legal_name": "ООО Игра", "inn": "7700000000"}]

    monkeypatch.setattr(buyer_hunt, "extract", fake_extract)

    result = buyer_hunt.hunt(
        ["q"],
        actor_id="apify/company-scraper",
        actor_input={"startUrls": ["https://studio.example"]},
    )

    assert result["profiles"] == [{"legal_name": "ООО Игра", "inn": "7700000000"}]
    assert seen == {
        "actor_id": "apify/company-scraper",
        "actor_input": {"startUrls": ["https://studio.example"]},
        "max_items": None,
        "wait_seconds": None,
    }


def test_an_actor_without_its_input_is_refused(exa_calls):
    with pytest.raises(ValueError, match="actor_input"):
        buyer_hunt.hunt(["q"], actor_id="apify/company-scraper")


def test_betting_is_not_searched_by_default():
    joined = " ".join(buyer_hunt.DEFAULT_QUERIES).lower()
    assert "казино" not in joined
    assert "ставки" not in joined


def test_hunt_plan_keeps_the_pool_id_on_each_page(exa_calls):
    _, answers = exa_calls
    query = Query(
        id="buyer.ads.esports",
        block="buyers.ads",
        text="реклама erid киберспорт",
    )
    answers[query.text] = [_page("https://brand.example")]

    result = buyer_hunt.hunt_plan([query])

    assert result["queries"] == ["buyer.ads.esports"]
    assert result["pages"][0]["query_used"] == "buyer.ads.esports"
    assert result["profiles"] == []
